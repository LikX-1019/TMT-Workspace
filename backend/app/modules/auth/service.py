"""Authentication application service: login, refresh, logout, current user.

Transaction and durability contracts:

- Success paths (login/refresh) only flush; the request transaction commits in
  ``get_db_session``.
- Security-critical failure paths (refresh reuse detection, refreshing with an
  inactive user, logout) revoke the token family and **commit inside this
  service** before raising, so a failed HTTP response can never roll the
  revocation back. ``LoginLogWriter`` uses an independent session for the same
  reason: login-failure evidence must survive the failed request.
"""

import ipaddress
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.exceptions import (
    AuthenticationError,
    RateLimitError,
    SessionRevokedError,
    ValidationError,
)
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_dummy_password,
    verify_password,
)
from app.modules.auth.models import LocalCredential, LoginLog, LoginResult, RefreshToken
from app.modules.auth.redis_store import AuthStateStore
from app.modules.auth.repository import LocalCredentialRepository, RefreshTokenRepository
from app.modules.auth.schemas import CurrentUserResponse, LoginRequest
from app.modules.rbac.service import AuthorizationService
from app.modules.users.models import AccountStatus, EmploymentStatus, User
from app.modules.users.repository import UserRepository

logger = logging.getLogger(__name__)

_MAX_LOGGED_USER_AGENT_LENGTH = 512

# Internal failure categories for login_logs only; never exposed to clients.
_FAILURE_UNKNOWN_USERNAME = "unknown_username"
_FAILURE_USER_DELETED = "user_deleted"
_FAILURE_ACCOUNT_DISABLED = "account_disabled"
_FAILURE_ACCOUNT_LOCKED = "account_locked"
_FAILURE_EMPLOYMENT_RESIGNED = "employment_resigned"
_FAILURE_NO_LOCAL_CREDENTIAL = "no_local_credential"
_FAILURE_BAD_PASSWORD = "bad_password"


@dataclass(slots=True)
class LoginOutcome:
    """Everything the API layer needs to answer a login/refresh request."""

    access_token: str
    expires_in: int
    refresh_token: str
    session_id: UUID


@dataclass(slots=True)
class AuthenticatedUser:
    """Request-scoped authenticated identity plus its session reference."""

    user: User
    session_id: UUID


@dataclass(slots=True)
class _CredentialCheck:
    """Result of evaluating one login attempt against user/credential state."""

    user: User | None = None
    credential: LocalCredential | None = None
    failure_reason: str | None = None


class LoginLogWriter:
    """Durably append login evidence in an independent short-lived session.

    Login failures raise HTTP errors, so request-scoped transactions would roll
    the evidence back. This writer owns its transaction; write failures are
    logged without credentials and never break the login response.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append(
        self,
        *,
        username: str,
        result: LoginResult,
        user_id: UUID | None,
        failure_reason: str | None,
        ip: str | None,
        user_agent: str | None,
    ) -> None:
        log = LoginLog(
            username=username[:64],
            result=result,
            user_id=user_id,
            failure_reason=failure_reason,
            ip=normalize_ip(ip),
            user_agent=user_agent[:_MAX_LOGGED_USER_AGENT_LENGTH]
            if user_agent is not None
            else None,
        )
        try:
            async with self._session_factory() as session:
                session.add(log)
                await session.commit()
        except Exception:
            logger.warning(
                "login log write failed for result=%s reason=%s",
                result.value,
                failure_reason,
                exc_info=True,
            )


class AuthService:
    """Enforce authentication rules and session lifecycle invariants."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        state_store: AuthStateStore,
        login_log_writer: LoginLogWriter,
    ) -> None:
        self._session = session
        self._settings = settings
        self._state_store = state_store
        self._login_logs = login_log_writer
        self._users = UserRepository(session)
        self._credentials = LocalCredentialRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)

    async def login(
        self, payload: LoginRequest, *, client_ip: str | None, user_agent: str | None
    ) -> LoginOutcome:
        """Authenticate local credentials and open a new refresh-token session.

        Unknown usernames, missing credentials, and wrong passwords all fail
        with the same generic error; only internal login logs distinguish them.
        """

        username = self._normalize_username(payload.username)
        if not username:
            raise ValidationError("Username is required.")

        counts = await self._state_store.login_failure_counts(
            username=username, client_ip=client_ip
        )
        if max(counts) >= self._settings.login_max_attempts:
            await self._log_attempt(
                LoginResult.RATE_LIMITED,
                username=username,
                user_id=None,
                failure_reason="rate_limited",
                client_ip=client_ip,
                user_agent=user_agent,
            )
            raise RateLimitError()

        check = await self._evaluate_credentials(username, payload.password)
        if check.failure_reason is not None:
            await self._state_store.record_login_failure(
                username=username,
                client_ip=client_ip,
                window_seconds=self._settings.login_window_seconds,
            )
            await self._log_attempt(
                LoginResult.FAILURE,
                username=username,
                user_id=check.user.id if check.user is not None else None,
                failure_reason=check.failure_reason,
                client_ip=client_ip,
                user_agent=user_agent,
            )
            raise AuthenticationError("Incorrect username or password.")

        assert check.user is not None
        assert check.credential is not None
        await self._maybe_rehash_password(check.credential, payload.password)

        outcome = await self._open_session(check.user, client_ip=client_ip, user_agent=user_agent)
        await self._state_store.clear_login_failures(username=username, client_ip=client_ip)
        await self._log_attempt(
            LoginResult.SUCCESS,
            username=username,
            user_id=check.user.id,
            failure_reason=None,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return outcome

    async def refresh(
        self, refresh_token: str, *, client_ip: str | None, user_agent: str | None
    ) -> LoginOutcome:
        """Rotate a refresh token and issue a new access token.

        The presented row is locked with ``SELECT ... FOR UPDATE`` inside the
        caller's transaction, so concurrent use of one token serializes: the
        first request rotates, every later request observes the revoked row and
        triggers reuse detection.
        """

        row = await self._refresh_tokens.get_by_token_hash_for_update(
            hash_refresh_token(refresh_token)
        )
        if row is None:
            raise AuthenticationError()

        now = utc_now()
        if row.revoked_at is not None or row.replaced_by_id is not None:
            await self._revoke_session_family(row.session_id, now)
            raise AuthenticationError("Refresh token is no longer valid.")
        if row.expires_at <= now:
            raise AuthenticationError()

        user = await self._users.get_by_id(row.user_id, include_deleted=True)
        if not _is_authenticatable(user):
            await self._revoke_session_family(row.session_id, now)
            raise AuthenticationError()

        if await self._state_store.is_session_revoked(row.session_id):
            await self._revoke_session_family(row.session_id, now)
            raise SessionRevokedError()

        replacement_token = generate_refresh_token()
        replacement = RefreshToken(
            user_id=row.user_id,
            session_id=row.session_id,
            token_hash=hash_refresh_token(replacement_token),
            issued_at=now,
            expires_at=now + self._refresh_ttl(),
            ip=normalize_ip(client_ip),
            user_agent=user_agent[:_MAX_LOGGED_USER_AGENT_LENGTH]
            if user_agent is not None
            else None,
        )
        await self._refresh_tokens.create(replacement)
        row.revoked_at = now
        row.replaced_by_id = replacement.id
        await self._session.flush()

        assert user is not None
        return self._issue_access_token(user, row.session_id, replacement_token)

    async def logout(self, refresh_token: str | None) -> UUID | None:
        """Revoke the presented token's family and return its session id.

        Idempotent and safe to call with a missing, unknown, or already revoked
        token: the cookie is cleared by the API layer regardless.
        """

        if refresh_token is None:
            return None
        row = await self._refresh_tokens.get_by_token_hash_for_update(
            hash_refresh_token(refresh_token)
        )
        if row is None:
            return None
        return await self._revoke_session_family(row.session_id, utc_now())

    async def get_current_user(self, access_token: str) -> AuthenticatedUser:
        """Resolve the authenticated identity behind one access token.

        Validates signature, expiry, and token type, then checks server-side
        session revocation and current account state. Stateless JWT expiry is
        never sufficient on its own.
        """

        try:
            claims = decode_access_token(
                access_token,
                secret_key=self._settings.secret_key.get_secret_value(),
                algorithm=self._settings.jwt_algorithm,
            )
        except Exception as error:
            raise AuthenticationError() from error

        try:
            user_id = UUID(str(claims["sub"]))
            session_id = UUID(str(claims["sid"]))
        except (KeyError, ValueError) as error:
            raise AuthenticationError() from error

        if await self._state_store.is_session_revoked(session_id):
            raise SessionRevokedError()

        user = await self._users.get_by_id(user_id, include_deleted=True)
        if not _is_authenticatable(user):
            raise AuthenticationError()

        assert user is not None
        return AuthenticatedUser(user=user, session_id=session_id)

    async def build_profile(self, user: User) -> CurrentUserResponse:
        """Compose the current-user profile with authorization and org data.

        Module dependency (documented): ``auth`` consumes the ``rbac`` public
        ``AuthorizationService`` contract to resolve role codes and effective
        permission codes. Authentication still answers only "who are you?";
        authorization state rides along as display data, not as a bypass.
        """

        authorization = AuthorizationService(self._session)
        role_codes = await authorization.get_role_codes(user.id)
        permission_codes = await authorization.get_effective_permission_codes(user.id)
        primary_department = await self._users.get_primary_department(user.id)
        primary_position = await self._users.get_primary_position(user.id)
        return CurrentUserResponse(
            id=user.id,
            employee_no=user.employee_no,
            username=user.username,
            name=user.name,
            email=user.email,
            mobile=user.mobile,
            employment_status=EmploymentStatus(user.employment_status.value),
            account_status=AccountStatus(user.account_status.value),
            roles=role_codes,
            permissions=sorted(permission_codes),
            primary_department=primary_department.department if primary_department else None,
            primary_position=primary_position.position if primary_position else None,
            last_login_at=user.last_login_at,
        )

    async def _evaluate_credentials(self, username: str, password: str) -> _CredentialCheck:
        """Evaluate one attempt against user state and local credential.

        Every rejection path burns one Argon2id verification so response timing
        does not reveal which check failed.
        """

        user = await self._users.get_any_by_username(username)
        if user is None:
            verify_dummy_password(password)
            return _CredentialCheck(failure_reason=_FAILURE_UNKNOWN_USERNAME)
        if user.deleted_at is not None:
            verify_dummy_password(password)
            return _CredentialCheck(user=user, failure_reason=_FAILURE_USER_DELETED)
        if user.account_status == AccountStatus.DISABLED:
            verify_dummy_password(password)
            return _CredentialCheck(user=user, failure_reason=_FAILURE_ACCOUNT_DISABLED)
        if user.account_status == AccountStatus.LOCKED:
            verify_dummy_password(password)
            return _CredentialCheck(user=user, failure_reason=_FAILURE_ACCOUNT_LOCKED)
        if user.employment_status == EmploymentStatus.RESIGNED:
            verify_dummy_password(password)
            return _CredentialCheck(user=user, failure_reason=_FAILURE_EMPLOYMENT_RESIGNED)

        credential = await self._credentials.get_by_user_id(user.id)
        if credential is None:
            verify_dummy_password(password)
            return _CredentialCheck(user=user, failure_reason=_FAILURE_NO_LOCAL_CREDENTIAL)
        if not verify_password(password, credential.password_hash):
            return _CredentialCheck(
                user=user, credential=credential, failure_reason=_FAILURE_BAD_PASSWORD
            )
        return _CredentialCheck(user=user, credential=credential, failure_reason=None)

    async def _maybe_rehash_password(self, credential: LocalCredential, password: str) -> None:
        """Upgrade password hash parameters transparently after a successful login.

        ``password_changed_at`` keeps its original value: the secret itself did
        not change, only its encoding.
        """

        if password_needs_rehash(credential.password_hash):
            credential.password_hash = hash_password(password)
            await self._session.flush()

    async def _open_session(
        self, user: User, *, client_ip: str | None, user_agent: str | None
    ) -> LoginOutcome:
        now = utc_now()
        session_id = uuid4()
        refresh_token = generate_refresh_token()
        token = RefreshToken(
            user_id=user.id,
            session_id=session_id,
            token_hash=hash_refresh_token(refresh_token),
            issued_at=now,
            expires_at=now + self._refresh_ttl(),
            ip=normalize_ip(client_ip),
            user_agent=user_agent[:_MAX_LOGGED_USER_AGENT_LENGTH]
            if user_agent is not None
            else None,
        )
        await self._refresh_tokens.create(token)
        user.last_login_at = now
        await self._session.flush()
        return self._issue_access_token(user, session_id, refresh_token)

    async def _revoke_session_family(self, session_id: UUID, now: datetime) -> UUID:
        """Revoke the whole token family durably, then flag the session in Redis.

        The commit happens here on purpose: callers raise an authentication
        error right after, and the request-scoped rollback must not undo the
        revocation. The Redis marker covers access tokens still in flight; its
        TTL spans the maximum remaining access-token lifetime.
        """

        await self._refresh_tokens.revoke_family(session_id, revoked_at=now)
        await self._session.commit()
        await self._state_store.revoke_session(
            session_id,
            ttl_seconds=self._settings.access_token_ttl_seconds + 60,
        )
        return session_id

    def _issue_access_token(self, user: User, session_id: UUID, refresh_token: str) -> LoginOutcome:
        access_token = create_access_token(
            user_id=user.id,
            session_id=session_id,
            secret_key=self._settings.secret_key.get_secret_value(),
            algorithm=self._settings.jwt_algorithm,
            ttl_minutes=self._settings.access_token_ttl_minutes,
        )
        return LoginOutcome(
            access_token=access_token,
            expires_in=self._settings.access_token_ttl_seconds,
            refresh_token=refresh_token,
            session_id=session_id,
        )

    async def _log_attempt(
        self,
        result: LoginResult,
        *,
        username: str,
        user_id: UUID | None,
        failure_reason: str | None,
        client_ip: str | None,
        user_agent: str | None,
    ) -> None:
        await self._login_logs.append(
            username=username,
            result=result,
            user_id=user_id,
            failure_reason=failure_reason,
            ip=client_ip,
            user_agent=user_agent,
        )

    def _refresh_ttl(self) -> timedelta:
        return timedelta(days=self._settings.refresh_token_ttl_days)

    @staticmethod
    def _normalize_username(username: str) -> str:
        """Apply the Phase 1A username normalization rule."""

        return username.strip().lower()


def _is_authenticatable(user: User | None) -> bool:
    """Report whether an account may authenticate right now.

    Only active accounts authenticate. ``on_leave`` stays allowed by default;
    resigned and soft-deleted employees are always denied.
    """

    return (
        user is not None
        and user.deleted_at is None
        and user.account_status == AccountStatus.ACTIVE
        and user.employment_status != EmploymentStatus.RESIGNED
    )


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_ip(value: str | None) -> str | None:
    """Return a valid IP literal for INET columns, or ``None``."""

    if value is None:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None
