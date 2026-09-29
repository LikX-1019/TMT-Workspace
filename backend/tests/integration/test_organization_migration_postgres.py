"""Migration contract against a guarded PostgreSQL database."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.db.base import Base
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.integration.conftest import isolated_database_url

pytestmark = pytest.mark.postgres

BUSINESS_TABLES = {
    "departments",
    "positions",
    "user_departments",
    "user_positions",
    "users",
}


def _run_alembic(*arguments: str) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=backend_root,
        env=os.environ.copy(),
        check=True,
    )


async def _load_scalar(connection: AsyncConnection, statement: str) -> int:
    return int(await connection.scalar(text(statement)))


async def test_migration_cycle_creates_expected_schema() -> None:
    url = isolated_database_url()
    reset_engine = create_async_engine(url)
    try:
        async with reset_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        await reset_engine.dispose()

    _run_alembic("upgrade", "head")
    _run_alembic("downgrade", "base")
    _run_alembic("upgrade", "head")

    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            tables = {
                row[0]
                for row in await connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            }
            foreign_keys = await _load_scalar(
                connection,
                "SELECT count(*) FROM information_schema.table_constraints "
                "WHERE table_schema = 'public' AND constraint_type = 'FOREIGN KEY'",
            )
            checks = await _load_scalar(
                connection,
                "SELECT count(*) FROM pg_constraint WHERE connamespace = 'public'::regnamespace "
                "AND contype = 'c'",
            )
            partial_indexes = await _load_scalar(
                connection,
                "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' "
                "AND indexname IN "
                "('uq_user_departments_user_primary', 'uq_user_positions_user_primary')",
            )
    finally:
        await engine.dispose()

    assert tables == BUSINESS_TABLES | {"alembic_version"}
    assert foreign_keys == 7
    assert checks == 5
    assert partial_indexes == 2
