"""Real PostgreSQL and Redis integration fixtures."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from app.core.config import Settings, get_settings
from app.db import models as db_models  # noqa: F401  (complete registry metadata)
from app.db.base import Base
from app.modules.auth.redis_store import LoginFailureCounts
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

pytestmark = pytest.mark.postgres


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip postgres-marked tests wholesale when no guarded test DB is configured."""

    if os.getenv("TMT_TEST_DATABASE_URL"):
        return
    skip_marker = pytest.mark.skip(reason="TMT_TEST_DATABASE_URL is not configured.")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip_marker)


def isolated_database_url() -> str:
    """Return a guarded URL for an isolated PostgreSQL test database."""

    raw_url = os.getenv("TMT_TEST_DATABASE_URL")
    if raw_url is None:
        pytest.skip("TMT_TEST_DATABASE_URL is not configured.")

    settings = Settings(_env_file=None)
    if settings.environment != "testing":
        pytest.fail("PostgreSQL integration tests require TMT_ENVIRONMENT=testing.")

    url = make_url(raw_url)
    database_name = url.database or ""
    allowed_name = database_name == "tmt_workspace_test" or database_name.startswith(
        "tmt_workspace_test_"
    )
    if (
        url.get_backend_name() != "postgresql"
        or url.get_driver_name() != "asyncpg"
        or not allowed_name
    ):
        pytest.fail(
            "Integration tests may only use postgresql+asyncpg tmt_workspace_test databases."
        )

    return raw_url


async def create_isolated_engine() -> AsyncEngine:
    """Return an engine after resetting the guarded test schema."""

    engine = create_async_engine(isolated_database_url())
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    return engine


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Provide one schema-isolated, transaction-scoped integration session."""

    engine = await create_isolated_engine()

    connection = await engine.connect()
    outer_transaction = await connection.begin()
    session_factory = async_sessionmaker(
        connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = session_factory()

    try:
        yield session
    finally:
        await session.close()
        await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
async def api_app() -> AsyncIterator[FastAPI]:
    """Application bound to a freshly reset test database."""

    engine = await create_isolated_engine()
    await engine.dispose()
    application_database = make_url(get_settings().database_url).database
    if application_database != make_url(isolated_database_url()).database:
        pytest.fail(
            "TMT_DATABASE_URL must point at the guarded test database for API tests; "
            f"got {application_database!r}."
        )

    from app.main import create_app

    application = create_app()
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def api_client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP client that keeps cookies across requests, like a browser."""

    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    """Real Redis client for the configured test database, cleaned per test."""

    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    await _delete_auth_keys(client)
    try:
        yield client
    finally:
        await _delete_auth_keys(client)
        await client.close()


async def _delete_auth_keys(client: Redis) -> None:
    keys = [key async for key in client.scan_iter(match="auth:*")]
    if keys:
        await client.delete(*keys)


@asynccontextmanager
async def committed_session() -> AsyncIterator[AsyncSession]:
    """Independent short-lived session for data that must be really committed.

    Use it for seeding or verifying state produced by components that own their
    engine/connection (the HTTP application, the CLI).
    """

    engine = create_async_engine(isolated_database_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


MANAGEMENT_PASSWORD = "Matrix-Passphrase-1!"


@pytest.fixture
async def management_accounts(api_client: AsyncClient) -> dict[str, str]:
    """管理 API 授权矩阵的共享账号：super_admin 持有者 + 无角色用户。

    返回 ``{"super_token", "plain_token", "super_id", "plain_id"}``。
    schema 由 ``api_client`` 重置；账号与目录通过独立会话真实提交。
    """

    from app.core.security import hash_password
    from app.db.base import utc_now
    from app.modules.auth.models import LocalCredential
    from app.modules.rbac.catalog import SUPER_ADMIN_ROLE_CODE
    from app.modules.rbac.service import AuthorizationService, PermissionCatalogService
    from app.modules.users.models import AccountStatus, EmploymentStatus, User

    async with committed_session() as session:
        await PermissionCatalogService(session).sync()
        user_ids: dict[str, UUID] = {}
        for username in ("matrix-super", "matrix-plain"):
            user = User(
                employee_no=f"E-{username}"[:32],
                username=username,
                name=username.title(),
                email=f"{username}@example.com",
                employment_status=EmploymentStatus.ACTIVE,
                account_status=AccountStatus.ACTIVE,
            )
            session.add(user)
            await session.flush()
            session.add(
                LocalCredential(
                    user_id=user.id,
                    password_hash=hash_password(MANAGEMENT_PASSWORD),
                    password_changed_at=utc_now(),
                )
            )
            user_ids[username] = user.id
        await session.commit()

    async with committed_session() as session:
        await AuthorizationService(session).assign_role(
            user_ids["matrix-super"], SUPER_ADMIN_ROLE_CODE
        )
        await session.commit()

    tokens: dict[str, str] = {}
    for username in ("matrix-super", "matrix-plain"):
        response = await api_client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": MANAGEMENT_PASSWORD},
        )
        assert response.status_code == 200, response.text
        tokens[username] = response.json()["data"]["access_token"]

    return {
        "super_token": tokens["matrix-super"],
        "plain_token": tokens["matrix-plain"],
        "super_id": str(user_ids["matrix-super"]),
        "plain_id": str(user_ids["matrix-plain"]),
    }


async def request_as(
    client: AsyncClient,
    token: str | None,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> Response:
    """以给定 token（None = 匿名）调用 JSON API。"""

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return await client.request(method, path, json=body, headers=headers)


class FakeAuthStateStore:
    """In-memory AuthStateStore for service-level PostgreSQL tests."""

    def __init__(self) -> None:
        self.failures: dict[str, int] = {}
        self.revoked_sessions: dict[UUID, int] = {}

    async def login_failure_counts(
        self, *, username: str, client_ip: str | None
    ) -> LoginFailureCounts:
        username_count = self.failures.get(f"user:{username}", 0)
        ip_count = self.failures.get(f"ip:{client_ip}", 0) if client_ip else 0
        return LoginFailureCounts(username=username_count, ip=ip_count)

    async def record_login_failure(
        self, *, username: str, client_ip: str | None, window_seconds: int
    ) -> None:
        del window_seconds
        self.failures[f"user:{username}"] = self.failures.get(f"user:{username}", 0) + 1
        if client_ip:
            self.failures[f"ip:{client_ip}"] = self.failures.get(f"ip:{client_ip}", 0) + 1

    async def clear_login_failures(self, *, username: str, client_ip: str | None) -> None:
        self.failures.pop(f"user:{username}", None)
        if client_ip:
            self.failures.pop(f"ip:{client_ip}", None)

    async def is_session_revoked(self, session_id: UUID) -> bool:
        return session_id in self.revoked_sessions

    async def revoke_session(self, session_id: UUID, *, ttl_seconds: int) -> None:
        self.revoked_sessions[session_id] = ttl_seconds
