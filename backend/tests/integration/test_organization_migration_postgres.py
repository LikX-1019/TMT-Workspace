"""Migration contract against a guarded PostgreSQL database.

Phase 3A adds ``0004_workspace_menu_foundation`` and a dedicated schema
parity check: the Alembic path and the ``Base.metadata.create_all`` path must
produce identical constraint sets for the workspace/menu tables, so the
integration fixtures (create_all) and production deployments (alembic) never
drift.
"""

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
    "local_credentials",
    "login_logs",
    "menus",
    "permissions",
    "positions",
    "refresh_tokens",
    "role_permissions",
    "roles",
    "user_departments",
    "user_positions",
    "user_roles",
    "users",
    "workspace_departments",
    "workspaces",
}

WORKSPACE_TABLES = ("workspaces", "workspace_departments", "menus")


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


async def _load_rows(connection: AsyncConnection, statement: str) -> set[tuple[str, str]]:
    rows = await connection.execute(text(statement))
    return {(str(row[0]), str(row[1])) for row in rows}


async def _reset_schema(url: str) -> None:
    """Drop every table (including alembic_version) for a clean cycle."""

    reset_engine = create_async_engine(url)
    try:
        async with reset_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        await reset_engine.dispose()


async def test_migration_cycle_creates_expected_schema() -> None:
    url = isolated_database_url()
    await _reset_schema(url)

    _run_alembic("upgrade", "head")
    _run_alembic("downgrade", "base")
    _run_alembic("upgrade", "head")
    # Phase 2A: 0003 must drop only RBAC tables; 0001/0002 schema survives.
    _run_alembic("downgrade", "0002_authentication")
    _run_alembic("upgrade", "head")
    # Phase 3A: 0004 must drop only workspace/menu tables; Phase 1/2 survive.
    _run_alembic("downgrade", "0003_rbac_foundation")
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
            auth_columns = await _load_scalar(
                connection,
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'users' "
                "AND column_name IN ('password_hash', 'refresh_token')",
            )
            rbac_constraints = await _load_scalar(
                connection,
                "SELECT count(*) FROM information_schema.table_constraints "
                "WHERE table_schema = 'public' AND constraint_name IN "
                "('uq_roles_code', 'uq_permissions_code', 'uq_user_roles_user_id_role_id', "
                "'pk_role_permissions', 'ck_roles_status', 'ck_roles_data_scope_type', "
                "'ck_permissions_kind', 'ck_permissions_status')",
            )
            workspace_constraints = await _load_scalar(
                connection,
                "SELECT count(*) FROM information_schema.table_constraints "
                "WHERE table_schema = 'public' AND constraint_name IN "
                "('uq_workspaces_code', 'uq_menus_workspace_id_code', "
                "'pk_workspace_departments', 'ck_workspaces_status', "
                "'ck_menus_status', 'ck_menus_menu_type', 'ck_menus_parent_not_self')",
            )
            workspace_fks = await _load_scalar(
                connection,
                "SELECT count(*) FROM information_schema.table_constraints "
                "WHERE table_schema = 'public' AND constraint_type = 'FOREIGN KEY' "
                "AND constraint_name IN "
                "('fk_menus_workspace_id_workspaces', 'fk_menus_parent_id_menus', "
                "'fk_workspace_departments_workspace_id_workspaces', "
                "'fk_workspace_departments_department_id_departments')",
            )
            workspace_menu_indexes = await _load_scalar(
                connection,
                "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' "
                "AND indexname IN "
                "('ix_workspaces_status', 'ix_workspaces_deleted_at', "
                "'ix_workspace_departments_department_id', "
                "'ix_menus_workspace_parent_sort', 'ix_menus_permission_code', "
                "'ix_menus_deleted_at')",
            )
    finally:
        await engine.dispose()

    assert tables == BUSINESS_TABLES | {"alembic_version"}
    # 16 through Phase 2C plus workspace_departments.workspace_id,
    # workspace_departments.department_id, menus.workspace_id, and
    # menus.parent_id.
    assert foreign_keys == 20
    # 10 through Phase 2A plus workspaces.status, menus.status,
    # menus.menu_type, and menus.parent_not_self.
    assert checks == 14
    assert partial_indexes == 2
    # Identity/credential separation holds: users never grows credential columns.
    assert auth_columns == 0
    # RBAC contracts: stable codes, association uniqueness, composite grants PK.
    assert rbac_constraints == 8
    # Workspace/menu contracts: stable codes, association composite PK,
    # lifecycle CHECKs, and self-parent CHECK.
    assert workspace_constraints == 7
    assert workspace_fks == 4
    assert workspace_menu_indexes == 6


async def test_migration_and_metadata_produce_identical_workspace_schema() -> None:
    """Alembic 与 create_all 两条建表路径对三张新表产出完全一致的 schema。"""

    url = isolated_database_url()
    await _reset_schema(url)
    _run_alembic("upgrade", "head")

    migration_engine = create_async_engine(url)
    try:
        async with migration_engine.connect() as connection:
            migration_constraints = await _load_rows(
                connection,
                "SELECT conrelid::regclass::text, conname FROM pg_constraint "
                "WHERE conrelid IN ('workspaces'::regclass, "
                "'workspace_departments'::regclass, 'menus'::regclass)",
            )
            migration_indexes = await _load_rows(
                connection,
                "SELECT tablename, indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename IN "
                "('workspaces', 'workspace_departments', 'menus')",
            )
            migration_columns = await _load_rows(
                connection,
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name IN "
                "('workspaces', 'workspace_departments', 'menus')",
            )
    finally:
        await migration_engine.dispose()

    # create_all 路径（integration fixtures 使用）。
    await _reset_schema(url)
    metadata_engine = create_async_engine(url)
    try:
        async with metadata_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with metadata_engine.connect() as connection:
            metadata_constraints = await _load_rows(
                connection,
                "SELECT conrelid::regclass::text, conname FROM pg_constraint "
                "WHERE conrelid IN ('workspaces'::regclass, "
                "'workspace_departments'::regclass, 'menus'::regclass)",
            )
            metadata_indexes = await _load_rows(
                connection,
                "SELECT tablename, indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename IN "
                "('workspaces', 'workspace_departments', 'menus')",
            )
            metadata_columns = await _load_rows(
                connection,
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name IN "
                "('workspaces', 'workspace_departments', 'menus')",
            )
    finally:
        await metadata_engine.dispose()

    assert migration_constraints == metadata_constraints, "constraint drift"
    assert migration_indexes == metadata_indexes, "index drift"
    assert migration_columns == metadata_columns, "column drift"
