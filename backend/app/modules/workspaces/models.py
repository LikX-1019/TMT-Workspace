"""Workspace and menu persistence models.

Phase 3A establishes the persistence foundation only:

- ``Workspace`` mirrors the code-owned registry (``registry.py``); the
  database stores operational state, display metadata, and associations.
- ``WorkspaceDepartment`` is a product/organization association. It NEVER
  grants access: workspace access comes only from
  ``RolePermission → workspace:<code>:access`` (unified RBAC, no second
  authorization table).
- ``Menu`` is navigation metadata inside one workspace. Menu
  ``permission_code`` drives UI visibility only; backend authorization never
  trusts menu visibility.

Department ≠ Workspace; Workspace ≠ backend domain module.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utc_now
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class WorkspaceStatus(StrEnum):
    """Workspace lifecycle. Disabled workspaces are temporarily unreachable."""

    ACTIVE = "active"
    DISABLED = "disabled"


class MenuStatus(StrEnum):
    """Menu lifecycle. Disabled menus drop out of navigation composition."""

    ACTIVE = "active"
    DISABLED = "disabled"


class MenuType(StrEnum):
    """Navigation node class.

    Only ``directory`` and ``page`` exist: the menu tree is navigation, not a
    button/action registry. Button-level visibility belongs to frontend
    ``hasPermission`` checks against the permission catalog, never to menu
    rows.
    """

    DIRECTORY = "directory"
    PAGE = "page"


def _enum_column(enum_type: type[StrEnum], column_name: str) -> Enum:
    """VARCHAR + CHECK 枚举列的平台统一写法（禁止 PostgreSQL native ENUM）。"""

    return Enum(
        enum_type,
        native_enum=False,
        length=32,
        values_callable=lambda enum: [item.value for item in enum],
        create_constraint=True,
        name=column_name,
        validate_strings=True,
    )


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One registered business workspace mirrored from the registry.

    ``code`` is the stable identifier from the code-owned registry and is
    never reused across the workspace's full lifetime (soft-deleted rows keep
    occupying their code). ``status`` and display metadata are the database's
    operational state; the registry remains the definition of what may exist.
    """

    # status 的 CHECK 由 Enum(create_constraint=True) 生成
    # （naming convention -> ck_workspaces_status），不再显式声明以免重复。
    __tablename__ = "workspaces"
    __table_args__ = (
        Index("ix_workspaces_status", "status"),
        Index("ix_workspaces_deleted_at", "deleted_at"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    home_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default=text("0"))
    status: Mapped[WorkspaceStatus] = mapped_column(
        _enum_column(WorkspaceStatus, "status"),
        default=WorkspaceStatus.ACTIVE,
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkspaceDepartment(Base):
    """Association between one workspace and one department.

    Pure many-to-many product/organization metadata with a composite primary
    key (no independent identity to cascade away). It confers no access:
    a user's workspace access comes only from role permissions. There is
    deliberately no ``is_default`` column — no product consumer exists for it.
    """

    # composite PK 即唯一性保证（role_permissions 同模式）；额外的 UNIQUE
    # 声明是冗余的，且 Alembic online DDL 会静默丢弃它，导致两条建表路径
    # 产生不一致 schema——因此不声明。
    __tablename__ = "workspace_departments"
    __table_args__ = (Index("ix_workspace_departments_department_id", "department_id"),)

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "workspaces.id",
            ondelete="RESTRICT",
            name="fk_workspace_departments_workspace_id_workspaces",
        ),
        primary_key=True,
    )
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "departments.id",
            ondelete="RESTRICT",
            name="fk_workspace_departments_department_id_departments",
        ),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class Menu(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Navigation metadata for one workspace.

    ``route_path`` is a workspace-relative path (``dashboard``, not
    ``/operation/dashboard``); the frontend composes full URLs. ``component_key``
    is a stable registry key the frontend resolves through its own component
    registry — the backend never stores or controls raw import paths.
    ``permission_code`` is optional UI-visibility metadata and must reference
    an active catalog permission when present.
    """

    # menu_type/status 的 CHECK 由 Enum(create_constraint=True) 生成
    # （ck_menus_menu_type / ck_menus_status）；parent_not_self 用裸约束名，
    # 由 naming convention 展开为 ck_menus_parent_not_self。
    __tablename__ = "menus"
    __table_args__ = (
        CheckConstraint("parent_id IS NULL OR id <> parent_id", name="parent_not_self"),
        UniqueConstraint("workspace_id", "code", name="uq_menus_workspace_id_code"),
        Index("ix_menus_workspace_parent_sort", "workspace_id", "parent_id", "sort"),
        Index("ix_menus_permission_code", "permission_code"),
        Index("ix_menus_deleted_at", "deleted_at"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT", name="fk_menus_workspace_id_workspaces"),
        nullable=False,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("menus.id", ondelete="RESTRICT", name="fk_menus_parent_id_menus"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    menu_type: Mapped[MenuType] = mapped_column(
        _enum_column(MenuType, "menu_type"),
        default=MenuType.PAGE,
        nullable=False,
    )
    route_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    component_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(128), nullable=True)
    permission_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default=text("0"))
    visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    status: Mapped[MenuStatus] = mapped_column(
        _enum_column(MenuStatus, "status"),
        default=MenuStatus.ACTIVE,
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
