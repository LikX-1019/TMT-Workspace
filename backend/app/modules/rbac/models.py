"""RBAC persistence models: roles, permissions, and their assignments.

Phase 2A establishes the persistence and resolution foundation only:

- ``Role`` / ``Permission`` carry lifecycle and display metadata.
- ``UserRole`` / ``RolePermission`` are pure grant associations (union-only,
  no deny semantics).
- ``Role.data_scope_type`` is stored configuration; no query enforcement
  exists yet (Phase 3+), and no ``role_data_scope_departments`` table is
  created until a consumer needs it.

Authentication answers "who are you?"; these tables answer "what can you
do?". The two aggregates stay separate by design.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
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

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utc_now


class RoleStatus(StrEnum):
    """Role lifecycle. Disabled roles stop contributing permissions."""

    ACTIVE = "active"
    DISABLED = "disabled"


class DataScopeType(StrEnum):
    """Stored row-visibility policy for a role; enforcement arrives later.

    ``CUSTOM`` will require a department-assignment table (Phase 3.5); the
    value is accepted and persisted now so the model is stable.
    """

    ALL = "all"
    DEPARTMENT = "department"
    DEPARTMENT_AND_CHILDREN = "department_and_children"
    SELF = "self"
    CUSTOM = "custom"


class PermissionKind(StrEnum):
    """Capability class a permission code represents.

    Phase 2A seeds only ``action`` permissions: every code must map to a real
    (current or planned) backend enforcement point. ``workspace`` and
    ``menu`` remain valid model values for later phases but no catalog data
    uses them.
    """

    ACTION = "action"
    WORKSPACE = "workspace"
    MENU = "menu"


class PermissionStatus(StrEnum):
    """Permission lifecycle. Disabled permissions stop being effective."""

    ACTIVE = "active"
    DISABLED = "disabled"


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named responsibility that bundles permission grants.

    ``code`` is the stable identifier referenced by code, seeds, and future
    integrations; display ``name`` may change freely. System roles are
    protected from ordinary disable/delete operations. Deletion is always
    soft: historical ``user_roles`` rows must keep resolving to the role row.
    """

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_scope_type: Mapped[DataScopeType] = mapped_column(
        Enum(
            DataScopeType,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
            create_constraint=True,
            name="data_scope_type",
            validate_strings=True,
        ),
        default=DataScopeType.SELF,
        server_default=DataScopeType.SELF.value,
        nullable=False,
    )
    sort: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    status: Mapped[RoleStatus] = mapped_column(
        Enum(
            RoleStatus,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
            create_constraint=True,
            name="status",
            validate_strings=True,
        ),
        default=RoleStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    is_system: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One backend capability identified by its code.

    Permission *definitions* are a development contract owned by
    ``app.modules.rbac.catalog``; the database only mirrors that catalog plus
    lifecycle status. Codes follow ``<namespace>:<resource>:<action>`` and
    never encode entity IDs.
    """

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[PermissionKind] = mapped_column(
        Enum(
            PermissionKind,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
            create_constraint=True,
            name="kind",
            validate_strings=True,
        ),
        default=PermissionKind.ACTION,
        nullable=False,
    )
    module: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PermissionStatus] = mapped_column(
        Enum(
            PermissionStatus,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
            create_constraint=True,
            name="status",
            validate_strings=True,
        ),
        default=PermissionStatus.ACTIVE,
        nullable=False,
        index=True,
    )


class UserRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Grant of one role to one user.

    The only path from users to permissions: there are no direct
    user-permission rows. ``assigned_by`` records the acting administrator
    (or the bootstrap operator); it is evidence, not an authorization input.
    """

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_id_role_id"),
        Index("ix_user_roles_role_id", "role_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_user_roles_user_id_users"),
        nullable=False,
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT", name="fk_user_roles_role_id_roles"),
        nullable=False,
    )
    assigned_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_user_roles_assigned_by_users"),
        nullable=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class RolePermission(Base):
    """Grant of one permission to one role.

    Composite primary key; associations are never cascaded away, so role
    soft-deletion keeps the historical grant rows intact.
    """

    __tablename__ = "role_permissions"

    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT", name="fk_role_permissions_role_id_roles"),
        primary_key=True,
    )
    permission_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "permissions.id",
            ondelete="RESTRICT",
            name="fk_role_permissions_permission_id_permissions",
        ),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
