"""Authentication service rules against real PostgreSQL."""

import asyncio
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.core.config import Settings
from app.core.exceptions import AuthenticationError, RateLimitError, SessionRevokedError
from app.core.security import hash_password, hash_refresh_token, password_needs_rehash
from app.db.base import utc_now
from app.modules.auth.models import LocalCredential, LoginLog, LoginResult, RefreshToken
from app.modules.auth.schemas import LoginRequest
from app.modules.auth.service import AuthService, LoginLogWriter
from app.modules.users.models import AccountStatus, EmploymentStatus, User
from argon2 import PasswordHasher as LegacyArgon2Hasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import FakeAuthStateStore, create_isolated_engine

pytestmark = pytest.mark.postgres

PASSWORD = "Sup3r-Secret-Passphrase!"


def make_settings() -> Settings:
    return Settings(_env_file=None)


async def make_service(session: AsyncSession) -> tuple[AuthService, FakeAuthStateStore]:
    """Build the service against the transactional test session."""

    writer = LoginLogWriter(
        async_sessionmaker(
            await session.connection(),
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
    )
    store = FakeAuthStateStore()
    service = AuthService(
        session, settings=make_settings(), state_store=store, login_log_writer=writer
    )
    return service, store


async def seed_user(
    session: AsyncSession,
    *,
    username: str = "alice",
    account_status: str = "active",
    employment_status: str = "active",
    deleted: bool = False,
    with_credential: bool = True,
    password_hash: str | None = None,
) -> User:
    user = User(
        employee_no=f"E-{username}"[:32],
        username=username,
        name=username.title(),
        employment_status=EmploymentStatus(employment_status),
        account_status=AccountStatus(account_status),
        deleted_at=utc_now() if deleted else None,
    )
    session.add(user)
    await session.flush()
    if with_credential:
        session.add(
            LocalCredential(
                user_id=user.id,
                password_hash=password_hash or hash_password(PASSWORD),
                password_changed_at=utc_now(),
            )
        )
    await session.flush()
    return user


async def seed_refresh_token(
    session: AsyncSession, user: User, *, expires_at: datetime | None = None
) -> str:
    """Insert one active refresh token and return its plaintext material."""

    from app.core.security import generate_refresh_token, hash_refresh_token

    token = generate_refresh_token()
    now = utc_now()
    session.add(
        RefreshToken(
            user_id=user.id,
            session_id=uuid4(),
            token_hash=hash_refresh_token(token),
            issued_at=now,
            expires_at=expires_at or now + timedelta(days=14),
        )
    )
    await session.flush()
    return token


async def family_rows(session: AsyncSession, session_id: UUID) -> list[RefreshToken]:
    result = await session.scalars(
        select(RefreshToken).where(RefreshToken.session_id == session_id)
    )
    return list(result)


async def latest_login_log(session: AsyncSession, username: str) -> LoginLog | None:
    result = await session.scalars(
        select(LoginLog)
        .where(LoginLog.username == username)
        .order_by(LoginLog.created_at.desc(), LoginLog.id.desc())
        .limit(1)
    )
    return result.first()


GENERIC_ERROR = "Incorrect username or password."


class TestLoginService:
    async def test_successful_login_opens_session_and_logs_success(
        self, db_session: AsyncSession
    ) -> None:
        await seed_user(db_session)
        service, store = await make_service(db_session)

        outcome = await service.login(
            LoginRequest(username="alice", password=PASSWORD),
            client_ip="10.0.0.8",
            user_agent="pytest-agent",
        )

        assert outcome.access_token
        assert outcome.expires_in == make_settings().access_token_ttl_seconds
        await db_session.flush()
        tokens = await family_rows(db_session, outcome.session_id)
        assert len(tokens) == 1
        assert tokens[0].ip == "10.0.0.8"
        log = await latest_login_log(db_session, "alice")
        assert log is not None
        assert log.result == LoginResult.SUCCESS
        assert store.failures == {}

    async def test_unknown_username_failure_is_generic(self, db_session: AsyncSession) -> None:
        service, store = await make_service(db_session)

        with pytest.raises(AuthenticationError) as error:
            await service.login(
                LoginRequest(username="ghost", password=PASSWORD),
                client_ip="10.0.0.1",
                user_agent=None,
            )
        assert error.value.message == GENERIC_ERROR
        assert store.failures["user:ghost"] == 1
        log = await latest_login_log(db_session, "ghost")
        assert log is not None
        assert log.failure_reason == "unknown_username"
        assert log.user_id is None

    async def test_wrong_password_failure_is_generic(self, db_session: AsyncSession) -> None:
        await seed_user(db_session)
        service, _store = await make_service(db_session)

        with pytest.raises(AuthenticationError) as unknown_error:
            await service.login(
                LoginRequest(username="ghost", password="whatever-placeholder"),
                client_ip=None,
                user_agent=None,
            )
        with pytest.raises(AuthenticationError) as wrong_password_error:
            await service.login(
                LoginRequest(username="alice", password="definitely-wrong-pass"),
                client_ip=None,
                user_agent=None,
            )

        assert unknown_error.value.message == wrong_password_error.value.message == GENERIC_ERROR
        log = await latest_login_log(db_session, "alice")
        assert log is not None
        assert log.failure_reason == "bad_password"
        assert log.result == LoginResult.FAILURE

    async def test_missing_credential_failure_is_generic(self, db_session: AsyncSession) -> None:
        await seed_user(db_session, username="sso-only", with_credential=False)
        service, _ = await make_service(db_session)

        with pytest.raises(AuthenticationError) as error:
            await service.login(
                LoginRequest(username="sso-only", password=PASSWORD),
                client_ip=None,
                user_agent=None,
            )
        assert error.value.message == GENERIC_ERROR

    @pytest.mark.parametrize(
        ("account_status", "employment_status", "deleted", "reason"),
        [
            ("disabled", "active", False, "account_disabled"),
            ("locked", "active", False, "account_locked"),
            ("active", "resigned", False, "employment_resigned"),
            ("active", "active", True, "user_deleted"),
        ],
    )
    async def test_inactive_accounts_cannot_authenticate(
        self,
        db_session: AsyncSession,
        account_status: str,
        employment_status: str,
        deleted: bool,
        reason: str,
    ) -> None:
        await seed_user(
            db_session,
            username=f"user-{reason}",
            account_status=account_status,
            employment_status=employment_status,
            deleted=deleted,
        )
        service, _ = await make_service(db_session)

        with pytest.raises(AuthenticationError) as error:
            await service.login(
                LoginRequest(username=f"user-{reason}", password=PASSWORD),
                client_ip=None,
                user_agent=None,
            )
        assert error.value.message == GENERIC_ERROR
        log = await latest_login_log(db_session, f"user-{reason}")
        assert log is not None
        assert log.failure_reason == reason

    async def test_rate_limited_attempts_are_rejected(self, db_session: AsyncSession) -> None:
        await seed_user(db_session, username="throttled")
        service, store = await make_service(db_session)
        settings = make_settings()
        store.failures["user:throttled"] = settings.login_max_attempts

        with pytest.raises(RateLimitError):
            await service.login(
                LoginRequest(username="throttled", password=PASSWORD),
                client_ip=None,
                user_agent=None,
            )
        log = await latest_login_log(db_session, "throttled")
        assert log is not None
        assert log.result == LoginResult.RATE_LIMITED

    async def test_successful_login_upgrades_outdated_hash_parameters(
        self, db_session: AsyncSession
    ) -> None:
        legacy_hasher = LegacyArgon2Hasher(time_cost=2, memory_cost=16384)
        user = await seed_user(
            db_session, username="legacy-hash", password_hash=legacy_hasher.hash(PASSWORD)
        )
        credential = await db_session.scalar(
            select(LocalCredential).where(LocalCredential.user_id == user.id)
        )
        assert credential is not None
        original_changed_at = credential.password_changed_at
        service, _ = await make_service(db_session)

        await service.login(
            LoginRequest(username="legacy-hash", password=PASSWORD),
            client_ip=None,
            user_agent=None,
        )

        assert password_needs_rehash(credential.password_hash) is False
        assert credential.password_changed_at == original_changed_at


class TestRefreshService:
    async def test_refresh_rotates_token_and_keeps_session(self, db_session: AsyncSession) -> None:
        user = await seed_user(db_session)
        token = await seed_refresh_token(db_session, user)
        await db_session.flush()
        stored = (
            await db_session.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id))
        ).one()
        service, _ = await make_service(db_session)

        outcome = await service.refresh(token, client_ip=None, user_agent=None)

        assert outcome.session_id == stored.session_id
        assert outcome.refresh_token != token
        await db_session.flush()
        rows = await family_rows(db_session, stored.session_id)
        assert len(rows) == 2
        old_row = next(row for row in rows if row.token_hash == hash_refresh_token(token))
        assert old_row.revoked_at is not None
        assert old_row.replaced_by_id == next(
            row.id for row in rows if row.token_hash != old_row.token_hash
        )

    async def test_expired_refresh_token_fails_without_family_revocation(
        self, db_session: AsyncSession
    ) -> None:
        user = await seed_user(db_session)
        token = await seed_refresh_token(
            db_session, user, expires_at=utc_now() - timedelta(minutes=1)
        )
        await db_session.flush()
        stored = (
            await db_session.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id))
        ).one()
        service, store = await make_service(db_session)

        with pytest.raises(AuthenticationError):
            await service.refresh(token, client_ip=None, user_agent=None)

        assert stored.revoked_at is None
        assert stored.session_id not in store.revoked_sessions

    async def test_unknown_refresh_token_fails(self, db_session: AsyncSession) -> None:
        service, _ = await make_service(db_session)
        with pytest.raises(AuthenticationError):
            await service.refresh("not-a-known-token-value", client_ip=None, user_agent=None)

    async def test_reused_refresh_token_revokes_whole_family(
        self, db_session: AsyncSession
    ) -> None:
        user = await seed_user(db_session)
        token = await seed_refresh_token(db_session, user)
        await db_session.flush()
        stored = (
            await db_session.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id))
        ).one()
        service, store = await make_service(db_session)

        first = await service.refresh(token, client_ip=None, user_agent=None)
        await db_session.flush()
        with pytest.raises(AuthenticationError):
            await service.refresh(token, client_ip=None, user_agent=None)

        rows = await family_rows(db_session, stored.session_id)
        assert all(row.revoked_at is not None for row in rows)
        assert stored.session_id in store.revoked_sessions
        assert first.session_id == stored.session_id

    async def test_refresh_with_revoked_session_revokes_family(
        self, db_session: AsyncSession
    ) -> None:
        user = await seed_user(db_session)
        token = await seed_refresh_token(db_session, user)
        await db_session.flush()
        stored = (
            await db_session.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id))
        ).one()
        service, store = await make_service(db_session)
        store.revoked_sessions[stored.session_id] = 600

        with pytest.raises(SessionRevokedError):
            await service.refresh(token, client_ip=None, user_agent=None)

        rows = await family_rows(db_session, stored.session_id)
        assert all(row.revoked_at is not None for row in rows)

    async def test_refresh_with_inactive_user_revokes_family(
        self, db_session: AsyncSession
    ) -> None:
        user = await seed_user(db_session)
        token = await seed_refresh_token(db_session, user)
        await db_session.flush()
        stored = (
            await db_session.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id))
        ).one()
        service, store = await make_service(db_session)

        user.account_status = AccountStatus.DISABLED
        await db_session.flush()
        with pytest.raises(AuthenticationError):
            await service.refresh(token, client_ip=None, user_agent=None)

        rows = await family_rows(db_session, stored.session_id)
        assert all(row.revoked_at is not None for row in rows)
        assert stored.session_id in store.revoked_sessions

    async def test_logout_revokes_family_and_is_idempotent(self, db_session: AsyncSession) -> None:
        user = await seed_user(db_session)
        token = await seed_refresh_token(db_session, user)
        await db_session.flush()
        stored = (
            await db_session.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id))
        ).one()
        service, store = await make_service(db_session)

        revoked_session = await service.logout(token)
        assert revoked_session == stored.session_id
        rows = await family_rows(db_session, stored.session_id)
        assert all(row.revoked_at is not None for row in rows)
        assert stored.session_id in store.revoked_sessions

        assert await service.logout(token) is not None  # repeat stays safe
        assert await service.logout(None) is None
        assert await service.logout("unknown-token-value") is None
        rows = await family_rows(db_session, stored.session_id)
        assert all(row.revoked_at is not None for row in rows)


class TestConcurrentRefresh:
    async def test_same_refresh_token_used_concurrently_has_single_winner(self) -> None:
        """Two concurrent rotations of one token: exactly one may win."""

        engine = await create_isolated_engine()
        try:
            setup_session = async_sessionmaker(engine, expire_on_commit=False)()
            async with setup_session.begin():
                user = await seed_user(setup_session, username="concurrent")
                token = await seed_refresh_token(setup_session, user)
            stored = await setup_session.scalar(
                select(RefreshToken).where(RefreshToken.user_id == user.id)
            )
            session_id = stored.session_id
            await setup_session.close()

            connection_a = await engine.connect()
            transaction_a = await connection_a.begin()
            session_a = async_sessionmaker(
                connection_a, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )()
            connection_b = await engine.connect()
            transaction_b = await connection_b.begin()
            session_b = async_sessionmaker(
                connection_b, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )()
            writer = LoginLogWriter(async_sessionmaker(engine, expire_on_commit=False))
            store = FakeAuthStateStore()
            service_a = AuthService(
                session_a, settings=make_settings(), state_store=store, login_log_writer=writer
            )
            service_b = AuthService(
                session_b, settings=make_settings(), state_store=store, login_log_writer=writer
            )

            async def attempt(service: AuthService, transaction: object) -> object:
                try:
                    outcome = await service.refresh(token, client_ip=None, user_agent=None)
                    await transaction.commit()
                    return outcome
                except AuthenticationError:
                    # The service already committed the reuse-detection revocation
                    # internally (production commit semantics); mirror that here so
                    # the outer transaction cannot roll the revocation back.
                    await transaction.commit()
                    return None

            results = await asyncio.gather(
                attempt(service_a, transaction_a),
                attempt(service_b, transaction_b),
            )
            await session_a.close()
            await session_b.close()
            await connection_a.close()
            await connection_b.close()

            successes = [result for result in results if result is not None]
            assert len(successes) == 1

            verification = async_sessionmaker(engine, expire_on_commit=False)()
            rows = await family_rows(verification, session_id)
            assert len(rows) == 2
            assert all(row.revoked_at is not None for row in rows)
            assert session_id in store.revoked_sessions
            await verification.close()
        finally:
            await engine.dispose()


class TestCurrentUserResolution:
    async def test_valid_access_token_resolves_identity(self, db_session: AsyncSession) -> None:
        from app.core.security import create_access_token

        user = await seed_user(db_session)
        service, store = await make_service(db_session)
        session_id = uuid4()
        settings = make_settings()
        token = create_access_token(
            user_id=user.id,
            session_id=session_id,
            secret_key=settings.secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            ttl_minutes=settings.access_token_ttl_minutes,
        )

        authenticated = await service.get_current_user(token)

        assert authenticated.user.id == user.id
        assert authenticated.session_id == session_id
        assert store.revoked_sessions == {}

    async def test_revoked_session_is_rejected(self, db_session: AsyncSession) -> None:
        from app.core.security import create_access_token

        user = await seed_user(db_session)
        service, store = await make_service(db_session)
        session_id = uuid4()
        store.revoked_sessions[session_id] = 60
        settings = make_settings()
        token = create_access_token(
            user_id=user.id,
            session_id=session_id,
            secret_key=settings.secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            ttl_minutes=settings.access_token_ttl_minutes,
        )

        with pytest.raises(SessionRevokedError):
            await service.get_current_user(token)

    async def test_disabled_user_with_valid_token_is_rejected(
        self, db_session: AsyncSession
    ) -> None:
        from app.core.security import create_access_token

        user = await seed_user(db_session)
        service, _ = await make_service(db_session)
        settings = make_settings()
        token = create_access_token(
            user_id=user.id,
            session_id=uuid4(),
            secret_key=settings.secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            ttl_minutes=settings.access_token_ttl_minutes,
        )

        user.account_status = AccountStatus.DISABLED
        await db_session.flush()
        with pytest.raises(AuthenticationError):
            await service.get_current_user(token)

    async def test_soft_deleted_user_with_valid_token_is_rejected(
        self, db_session: AsyncSession
    ) -> None:
        from app.core.security import create_access_token

        user = await seed_user(db_session)
        service, _ = await make_service(db_session)
        settings = make_settings()
        token = create_access_token(
            user_id=user.id,
            session_id=uuid4(),
            secret_key=settings.secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            ttl_minutes=settings.access_token_ttl_minutes,
        )

        user.deleted_at = utc_now()
        await db_session.flush()
        with pytest.raises(AuthenticationError):
            await service.get_current_user(token)

    async def test_on_leave_user_still_authenticates(self, db_session: AsyncSession) -> None:
        from app.core.security import create_access_token

        user = await seed_user(db_session, username="onleave", employment_status="on_leave")
        service, _ = await make_service(db_session)
        settings = make_settings()
        token = create_access_token(
            user_id=user.id,
            session_id=uuid4(),
            secret_key=settings.secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            ttl_minutes=settings.access_token_ttl_minutes,
        )

        authenticated = await service.get_current_user(token)
        assert authenticated.user.id == user.id


class TestTokenMaterialHygiene:
    async def test_refresh_tokens_never_store_plaintext(self, db_session: AsyncSession) -> None:
        user = await seed_user(db_session)
        token = await seed_refresh_token(db_session, user)
        await db_session.flush()
        service, _ = await make_service(db_session)

        outcome = await service.refresh(token, client_ip=None, user_agent=None)

        rows = await db_session.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id))
        stored_hashes = {row.token_hash for row in rows}
        assert token not in stored_hashes
        assert outcome.refresh_token not in stored_hashes
        assert all(len(value) == 64 for value in stored_hashes)

    async def test_no_plaintext_password_is_ever_persisted(self, db_session: AsyncSession) -> None:
        user = await seed_user(db_session, username="hygiene")
        credential = await db_session.scalar(
            select(LocalCredential).where(LocalCredential.user_id == user.id)
        )

        assert credential is not None
        assert PASSWORD not in credential.password_hash
        assert credential.password_hash.startswith("$argon2id$")
