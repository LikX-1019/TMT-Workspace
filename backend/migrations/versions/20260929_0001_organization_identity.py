"""Organization and identity persistence foundation.

Revision ID: 0001_organization_identity
Revises:
Create Date: 2026-09-29 00:00:00 UTC
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_organization_identity"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


timestamp = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_no", sa.String(length=32), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("mobile", sa.String(length=32), nullable=True),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column("employment_status", sa.String(length=32), nullable=False),
        sa.Column("account_status", sa.String(length=32), nullable=False),
        sa.Column("primary_supervisor_id", sa.Uuid(), nullable=True),
        sa.Column("last_login_at", timestamp, nullable=True),
        sa.Column("deleted_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint(
            "employment_status IN ('active', 'on_leave', 'resigned')",
            name=op.f("ck_users_employment_status"),
        ),
        sa.CheckConstraint(
            "account_status IN ('active', 'disabled', 'locked')",
            name=op.f("ck_users_account_status"),
        ),
        sa.ForeignKeyConstraint(
            ["primary_supervisor_id"],
            ["users.id"],
            name=op.f("fk_users_primary_supervisor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("employee_no", name=op.f("uq_users_employee_no")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("mobile", name=op.f("uq_users_mobile")),
    )
    op.create_index(op.f("ix_users_account_status"), "users", ["account_status"], unique=False)
    op.create_index(
        op.f("ix_users_employment_status"), "users", ["employment_status"], unique=False
    )
    op.create_index(
        op.f("ix_users_primary_supervisor_id"),
        "users",
        ["primary_supervisor_id"],
        unique=False,
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("sort", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("deleted_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name=op.f("ck_positions_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_positions")),
        sa.UniqueConstraint("code", name=op.f("uq_positions_code")),
    )
    op.create_index(op.f("ix_positions_deleted_at"), "positions", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_positions_status"), "positions", ["status"], unique=False)

    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("leader_id", sa.Uuid(), nullable=True),
        sa.Column("sort", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("deleted_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.CheckConstraint(
            "parent_id IS NULL OR id <> parent_id",
            name=op.f("ck_departments_parent_not_self"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name=op.f("ck_departments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["departments.id"],
            name=op.f("fk_departments_parent_id_departments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["leader_id"],
            ["users.id"],
            name=op.f("fk_departments_leader_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
        sa.UniqueConstraint("code", name=op.f("uq_departments_code")),
    )
    op.create_index(op.f("ix_departments_deleted_at"), "departments", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_departments_leader_id"), "departments", ["leader_id"], unique=False)
    op.create_index(op.f("ix_departments_parent_id"), "departments", ["parent_id"], unique=False)
    op.create_index(op.f("ix_departments_status"), "departments", ["status"], unique=False)

    op.create_table(
        "user_positions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("position_id", sa.Uuid(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_positions_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["positions.id"],
            name=op.f("fk_user_positions_position_id_positions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_positions")),
        sa.UniqueConstraint(
            "user_id",
            "position_id",
            name=op.f("uq_user_positions_user_id_position_id"),
        ),
    )
    op.create_index(
        op.f("ix_user_positions_position_id"), "user_positions", ["position_id"], unique=False
    )
    op.create_index(
        "uq_user_positions_user_primary",
        "user_positions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_primary IS TRUE"),
    )

    op.create_table(
        "user_departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_departments_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name=op.f("fk_user_departments_department_id_departments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_departments")),
        sa.UniqueConstraint(
            "user_id",
            "department_id",
            name=op.f("uq_user_departments_user_id_department_id"),
        ),
    )
    op.create_index(
        op.f("ix_user_departments_department_id"),
        "user_departments",
        ["department_id"],
        unique=False,
    )
    op.create_index(
        "uq_user_departments_user_primary",
        "user_departments",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_primary IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_departments_user_primary", table_name="user_departments")
    op.drop_index(op.f("ix_user_departments_department_id"), table_name="user_departments")
    op.drop_table("user_departments")

    op.drop_index("uq_user_positions_user_primary", table_name="user_positions")
    op.drop_index(op.f("ix_user_positions_position_id"), table_name="user_positions")
    op.drop_table("user_positions")

    op.drop_index(op.f("ix_departments_status"), table_name="departments")
    op.drop_index(op.f("ix_departments_parent_id"), table_name="departments")
    op.drop_index(op.f("ix_departments_leader_id"), table_name="departments")
    op.drop_index(op.f("ix_departments_deleted_at"), table_name="departments")
    op.drop_table("departments")

    op.drop_index(op.f("ix_positions_status"), table_name="positions")
    op.drop_index(op.f("ix_positions_deleted_at"), table_name="positions")
    op.drop_table("positions")

    op.drop_index(op.f("ix_users_primary_supervisor_id"), table_name="users")
    op.drop_index(op.f("ix_users_employment_status"), table_name="users")
    op.drop_index(op.f("ix_users_account_status"), table_name="users")
    op.drop_table("users")
