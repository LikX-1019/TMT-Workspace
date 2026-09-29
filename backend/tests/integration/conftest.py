"""Real PostgreSQL integration fixtures."""

import os
from collections.abc import AsyncIterator

import pytest
from app.core.config import Settings
from app.db.base import Base
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.postgres


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


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Provide one schema-isolated, transaction-scoped integration session."""

    engine = create_async_engine(isolated_database_url())
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

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
