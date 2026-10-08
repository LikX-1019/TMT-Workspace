"""Workspace and menu foundation: workspaces, workspace_departments, menus.

Revision ID: 0004_workspace_menu_foundation
Revises: 0003_rbac_foundation
Create Date: 2026-09-29 00:00:00 UTC

Phase 3A persistence foundation only — no workspace/menu management API and
no navigation endpoint exist yet; rows are created through the code-owned
workspace registry sync (``sync-workspaces``) and service/test fixtures.

Lifecycle enums (workspace status, menu status, menu type) use
VARCHAR + CHECK constraints per the platform enum policy; PostgreSQL native
ENUM types are avoided. ``workspace_departments`` is a pure many-to-many
association with a composite primary key and deliberately no ``is_default``
column (no product consumer). ``menus.parent_id`` is an adjacency list with a
self-parent CHECK; cycle prevention beyond self-reference lives in the
service (recursive CTE). Every foreign key is ON DELETE RESTRICT.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_workspace_menu_foundation"
down_revision: str | None = "0003_rbac_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

timestamp = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=128), nullable=True),
        sa.Column("home_path", sa.String(length=256), nullable=True),
        sa.Column("sort", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("deleted_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint("status IN ('active', 'disabled')", name=op.f("ck_workspaces_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("code", name=op.f("uq_workspaces_code")),
    )
    op.create_index("ix_workspaces_status", "workspaces", ["status"], unique=False)
    op.create_index("ix_workspaces_deleted_at", "workspaces", ["deleted_at"], unique=False)

    op.create_table(
        "workspace_departments",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_departments_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name=op.f("fk_workspace_departments_department_id_departments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "department_id", name=op.f("pk_workspace_departments")
        ),
    )
    op.create_index(
        "ix_workspace_departments_department_id",
        "workspace_departments",
        ["department_id"],
        unique=False,
    )

    op.create_table(
        "menus",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("menu_type", sa.String(length=32), nullable=False),
        sa.Column("route_path", sa.String(length=256), nullable=True),
        sa.Column("component_key", sa.String(length=128), nullable=True),
        sa.Column("icon", sa.String(length=128), nullable=True),
        sa.Column("permission_code", sa.String(length=128), nullable=True),
        sa.Column("sort", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("visible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("deleted_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint(
            "parent_id IS NULL OR id <> parent_id", name=op.f("ck_menus_parent_not_self")
        ),
        sa.CheckConstraint("menu_type IN ('directory', 'page')", name=op.f("ck_menus_menu_type")),
        sa.CheckConstraint("status IN ('active', 'disabled')", name=op.f("ck_menus_status")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_menus_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["menus.id"], name=op.f("fk_menus_parent_id_menus"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_menus")),
        sa.UniqueConstraint("workspace_id", "code", name=op.f("uq_menus_workspace_id_code")),
    )
    op.create_index(
        "ix_menus_workspace_parent_sort",
        "menus",
        ["workspace_id", "parent_id", "sort"],
        unique=False,
    )
    op.create_index("ix_menus_permission_code", "menus", ["permission_code"], unique=False)
    op.create_index("ix_menus_deleted_at", "menus", ["deleted_at"], unique=False)


def downgrade() -> None:
    # 0004 only ever owns the three tables below; Phase 1/2 schema is untouched.
    op.drop_index("ix_menus_deleted_at", table_name="menus")
    op.drop_index("ix_menus_permission_code", table_name="menus")
    op.drop_index("ix_menus_workspace_parent_sort", table_name="menus")
    op.drop_table("menus")
    op.drop_index("ix_workspace_departments_department_id", table_name="workspace_departments")
    op.drop_table("workspace_departments")
    op.drop_index("ix_workspaces_deleted_at", table_name="workspaces")
    op.drop_index("ix_workspaces_status", table_name="workspaces")
    op.drop_table("workspaces")
