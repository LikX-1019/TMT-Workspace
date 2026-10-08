"""Authentication API contract tests over real PostgreSQL and Redis."""

from uuid import uuid4

import pytest
from app.core.config import get_settings
from app.core.redis import get_redis_client
from app.core.security import create_access_token, hash_password
from app.db.base import utc_now
from app.modules.auth.models import LocalCredential, LoginLog, LoginResult
from app.modules.auth.redis_store import RedisAuthStateStore
from app.modules.departments.models import Department
from app.modules.positions.models import Position
from app.modules.users.models import (
    AccountStatus,
    EmploymentStatus,
    User,
    UserDepartment,
    UserPosition,
)
from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import select

from tests.integration.conftest import committed_session

pytestmark = pytest.mark.postgres

PASSWORD = "Sup3r-Secret-Passphrase!"
GENERIC_ERROR = "Incorrect username or password."


@pytest.fixture(autouse=True)
async def clean_redis_state(redis_client: Redis) -> None:
    """Isolate every API test from login-counter residue in Redis."""

    return


async def seed_user(
    *,
    username: str = "alice",
    password: str = PASSWORD,
    account_status: str = "active",
    employment_status: str = "active",
    deleted: bool = False,
    with_credential: bool = True,
    with_primary_department: bool = False,
    with_primary_position: bool = False,
) -> None:
    """Create committed fixture data through an independent session."""

    async with committed_session() as session:
        user = User(
            employee_no=f"E-{username}"[:32],
            username=username,
            name=username.title(),
            email=f"{username}@example.com",
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
                    password_hash=hash_password(password),
                    password_changed_at=utc_now(),
                )
            )
        if with_primary_department:
            department = Department(name="Engineering", code=f"eng-{username}"[:64])
            session.add(department)
            await session.flush()
            session.add(
                UserDepartment(user_id=user.id, department_id=department.id, is_primary=True)
            )
        if with_primary_position:
            position = Position(name="Engineer", code=f"eng-pos-{username}"[:64])
            session.add(position)
            await session.flush()
            session.add(UserPosition(user_id=user.id, position_id=position.id, is_primary=True))
        await session.commit()


async def login(client: AsyncClient, username: str, password: str) -> Response:
    return await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


class TestLoginContract:
    async def test_login_success_returns_access_token_and_refresh_cookie(
        self, api_client: AsyncClient
    ) -> None:
        await seed_user(username="login-ok")

        response = await login(api_client, "login-ok", PASSWORD)

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["token_type"] == "bearer"
        assert body["data"]["expires_in"] == get_settings().access_token_ttl_seconds
        assert body["data"]["access_token"]
        assert "refresh_token" not in body["data"]

        cookie = response.headers["set-cookie"]
        assert f"{get_settings().refresh_cookie_name}=" in cookie
        assert "HttpOnly" in cookie
        assert "samesite=lax" in cookie.lower()
        assert f"Path={get_settings().refresh_cookie_path}" in cookie
        assert "Secure" not in cookie  # testing environment runs over plain HTTP

    async def test_login_failures_share_one_generic_error(self, api_client: AsyncClient) -> None:
        await seed_user(username="no-cred", with_credential=False)

        unknown = await login(api_client, "ghost-user", PASSWORD)
        wrong_password = await login(api_client, "no-cred", "totally-wrong-pass-1")
        no_credential = await login(api_client, "no-cred", PASSWORD)

        for response in (unknown, wrong_password, no_credential):
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"
            assert response.json()["error"]["message"] == GENERIC_ERROR

    async def test_disabled_locked_resigned_deleted_users_cannot_login(
        self, api_client: AsyncClient
    ) -> None:
        for username, kwargs in [
            ("disabled-user", {"account_status": "disabled"}),
            ("locked-user", {"account_status": "locked"}),
            ("resigned-user", {"employment_status": "resigned"}),
            ("deleted-user", {"deleted": True}),
        ]:
            await seed_user(username=username, **kwargs)
            response = await login(api_client, username, PASSWORD)
            assert response.status_code == 401, username
            assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"

    async def test_on_leave_user_may_login(self, api_client: AsyncClient) -> None:
        await seed_user(username="on-leave-user", employment_status="on_leave")

        response = await login(api_client, "on-leave-user", PASSWORD)

        assert response.status_code == 200

    async def test_failed_login_writes_internal_evidence(self, api_client: AsyncClient) -> None:
        await seed_user(username="evidence")
        await login(api_client, "evidence", "definitely-wrong-pass")

        async with committed_session() as session:
            log = await session.scalar(select(LoginLog).where(LoginLog.username == "evidence"))
            assert log is not None
            assert log.result == LoginResult.FAILURE
            assert log.failure_reason == "bad_password"
            # Credential material never lands in the evidence table.
            columns = {column.name for column in LoginLog.__table__.columns}
            assert not any("password" in name or "token" in name for name in columns)

    async def test_login_validation_rejects_missing_fields(self, api_client: AsyncClient) -> None:
        response = await api_client.post("/api/v1/auth/login", json={"username": "x"})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "REQUEST_VALIDATION_FAILED"


class TestCurrentUserContract:
    async def test_me_returns_identity_with_primary_assignments(
        self, api_client: AsyncClient
    ) -> None:
        await seed_user(
            username="me-user",
            with_primary_department=True,
            with_primary_position=True,
        )
        login_response = await login(api_client, "me-user", PASSWORD)
        token = login_response.json()["data"]["access_token"]

        response = await api_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["username"] == "me-user"
        assert data["employment_status"] == "active"
        assert data["account_status"] == "active"
        assert data["primary_department"]["name"] == "Engineering"
        assert data["primary_position"]["name"] == "Engineer"
        # Phase 2A: authorization state rides along as display data.
        assert data["roles"] == []  # seeded without role assignments
        assert data["permissions"] == []

    async def test_me_requires_token(self, api_client: AsyncClient) -> None:
        response = await api_client.get("/api/v1/auth/me")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"
        assert response.headers["www-authenticate"] == "Bearer"

    async def test_me_rejects_invalid_token(self, api_client: AsyncClient) -> None:
        response = await api_client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
        )

        assert response.status_code == 401

    async def test_me_rejects_token_signed_by_other_secret(self, api_client: AsyncClient) -> None:
        forged = create_access_token(
            user_id=uuid4(),
            session_id=uuid4(),
            secret_key="attacker-controlled-secret-value-32b",
            algorithm="HS256",
            ttl_minutes=30,
        )

        response = await api_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}
        )

        assert response.status_code == 401

    async def test_me_rejects_disabled_user_with_valid_token(self, api_client: AsyncClient) -> None:
        await seed_user(username="disable-me")
        login_response = await login(api_client, "disable-me", PASSWORD)
        token = login_response.json()["data"]["access_token"]

        async with committed_session() as session:
            user = await session.scalar(select(User).where(User.username == "disable-me"))
            assert user is not None
            user.account_status = AccountStatus.DISABLED
            await session.commit()

        response = await api_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"


class TestRefreshContract:
    async def test_refresh_rotates_cookie_and_access_token(self, api_client: AsyncClient) -> None:
        await seed_user(username="rotator")
        first = await login(api_client, "rotator", PASSWORD)
        first_token = first.json()["data"]["access_token"]
        first_cookie = api_client.cookies.get(get_settings().refresh_cookie_name)
        assert first_cookie is not None

        response = await api_client.post("/api/v1/auth/refresh")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["access_token"]
        assert body["data"]["access_token"] != first_token
        assert "refresh_token" not in body["data"]
        rotated_cookie = api_client.cookies.get(get_settings().refresh_cookie_name)
        assert rotated_cookie is not None
        assert rotated_cookie != first_cookie

    async def test_refresh_without_cookie_fails(self, api_client: AsyncClient) -> None:
        response = await api_client.post(
            "/api/v1/auth/refresh", headers={"origin": "http://localhost:5173"}
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"

    async def test_reused_refresh_token_revokes_family_via_api(
        self, api_client: AsyncClient
    ) -> None:
        await seed_user(username="reuser")
        await login(api_client, "reuser", PASSWORD)
        original_cookie = api_client.cookies.get(get_settings().refresh_cookie_name)
        assert original_cookie is not None

        first_refresh = await api_client.post("/api/v1/auth/refresh")
        assert first_refresh.status_code == 200
        latest_token = first_refresh.json()["data"]["access_token"]

        # Replay the pre-rotation cookie: reuse detection must revoke the family.
        api_client.cookies.set(get_settings().refresh_cookie_name, original_cookie)
        replay = await api_client.post("/api/v1/auth/refresh")
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "AUTHENTICATION_FAILED"

        # Even the newest access token of that family is dead (server-side state).
        me_response = await api_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {latest_token}"}
        )
        assert me_response.status_code == 401
        assert me_response.json()["error"]["code"] == "SESSION_REVOKED"

    async def test_refresh_rejects_disallowed_origin(self, api_client: AsyncClient) -> None:
        await seed_user(username="origin-check")
        await login(api_client, "origin-check", PASSWORD)

        response = await api_client.post(
            "/api/v1/auth/refresh", headers={"origin": "https://evil.example"}
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AUTHORIZATION_FAILED"

    async def test_refresh_allows_allowed_origin(self, api_client: AsyncClient) -> None:
        await seed_user(username="origin-allowed")
        await login(api_client, "origin-allowed", PASSWORD)

        response = await api_client.post(
            "/api/v1/auth/refresh", headers={"origin": "http://localhost:5173"}
        )

        assert response.status_code == 200


class TestLogoutContract:
    async def test_logout_revokes_session_and_clears_cookie(self, api_client: AsyncClient) -> None:
        await seed_user(username="logout-user")
        first = await login(api_client, "logout-user", PASSWORD)
        access_token = first.json()["data"]["access_token"]

        response = await api_client.post("/api/v1/auth/logout")

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "ok"
        cleared = response.headers["set-cookie"]
        assert "Max-Age=0" in cleared
        assert "HttpOnly" in cleared

        refresh_response = await api_client.post("/api/v1/auth/refresh")
        assert refresh_response.status_code == 401

        me_response = await api_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
        )
        assert me_response.status_code == 401
        assert me_response.json()["error"]["code"] == "SESSION_REVOKED"

    async def test_logout_is_safe_without_cookie_and_repeatable(
        self, api_client: AsyncClient
    ) -> None:
        first = await api_client.post("/api/v1/auth/logout")
        second = await api_client.post("/api/v1/auth/logout")

        assert first.status_code == 200
        assert second.status_code == 200


class TestBruteForceProtection:
    async def test_username_threshold_locks_login_attempts(
        self, api_client: AsyncClient, redis_client: Redis
    ) -> None:
        username = f"bruteforce-{uuid4().hex[:8]}"
        await seed_user(username=username)
        settings = get_settings()

        statuses = [
            (await login(api_client, username, "wrong-password-value")).status_code
            for _ in range(settings.login_max_attempts + 1)
        ]

        assert statuses[: settings.login_max_attempts] == [401] * settings.login_max_attempts
        assert statuses[settings.login_max_attempts] == 429

        # A locked context rejects even the correct password.
        locked_with_valid_password = await login(api_client, username, PASSWORD)
        assert locked_with_valid_password.status_code == 429

        # Counting is per normalized username: another username has its own counter.
        store = RedisAuthStateStore(get_redis_client())
        other_counts = await store.login_failure_counts(
            username=f"other-{username}", client_ip=None
        )
        assert other_counts.username == 0

    async def test_successful_login_resets_failure_counters(
        self, api_client: AsyncClient, redis_client: Redis
    ) -> None:
        username = f"reset-{uuid4().hex[:8]}"
        await seed_user(username=username)

        await login(api_client, username, "wrong-password-value")
        success = await login(api_client, username, PASSWORD)
        assert success.status_code == 200

        store = RedisAuthStateStore(get_redis_client())
        counts = await store.login_failure_counts(username=username, client_ip=None)
        assert counts.username == 0

    async def test_rate_limited_response_is_generic(self, api_client: AsyncClient) -> None:
        username = f"ratelimited-{uuid4().hex[:8]}"
        await seed_user(username=username)
        settings = get_settings()

        for _ in range(settings.login_max_attempts):
            await login(api_client, username, "wrong-password-value")
        response = await login(api_client, username, "wrong-password-value")

        assert response.status_code == 429
        body = response.json()
        assert body["error"]["code"] == "RATE_LIMITED"
        assert "username" not in body["error"]["message"].lower()
