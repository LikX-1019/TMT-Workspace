"""User and organization assignment persistence models."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.departments.models import Department
from app.modules.positions.models import Position


class EmploymentStatus(StrEnum):
    """Employment lifecycle, independent of authentication account state."""

    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    RESIGNED = "resigned"


class AccountStatus(StrEnum):
    """Authentication account lifecycle managed by Phase 1B workflows."""

    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An employee identity; authentication credentials are a future aggregate."""

    __tablename__ = "users"

    employee_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True, unique=True)
    mobile: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        Enum(
            EmploymentStatus,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
            create_constraint=True,
            name="employment_status",
            validate_strings=True,
        ),
        default=EmploymentStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    account_status: Mapped[AccountStatus] = mapped_column(
        Enum(
            AccountStatus,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
            create_constraint=True,
            name="account_status",
            validate_strings=True,
        ),
        default=AccountStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    primary_supervisor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_users_primary_supervisor_id_users"),
        nullable=True,
        index=True,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    supervisor: Mapped["User | None"] = relationship(remote_side="User.id")
    department_assignments: Mapped[list["UserDepartment"]] = relationship(back_populates="user")
    position_assignments: Mapped[list["UserPosition"]] = relationship(back_populates="user")


class UserDepartment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's membership in a department."""

    __tablename__ = "user_departments"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "department_id", name="uq_user_departments_user_id_department_id"
        ),
        Index(
            "uq_user_departments_user_primary",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary IS TRUE"),
        ),
        Index("ix_user_departments_department_id", "department_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_user_departments_user_id_users"),
        nullable=False,
    )
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "departments.id",
            ondelete="RESTRICT",
            name="fk_user_departments_department_id_departments",
        ),
        nullable=False,
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        server_default=text("false"),
    )

    user: Mapped[User] = relationship(back_populates="department_assignments")
    department: Mapped[Department] = relationship()


class UserPosition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's assignment to an organizational position."""

    __tablename__ = "user_positions"
    __table_args__ = (
        UniqueConstraint("user_id", "position_id", name="uq_user_positions_user_id_position_id"),
        Index(
            "uq_user_positions_user_primary",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary IS TRUE"),
        ),
        Index("ix_user_positions_position_id", "position_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_user_positions_user_id_users"),
        nullable=False,
    )
    position_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "positions.id",
            ondelete="RESTRICT",
            name="fk_user_positions_position_id_positions",
        ),
        nullable=False,
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        server_default=text("false"),
    )

    user: Mapped[User] = relationship(back_populates="position_assignments")
    position: Mapped[Position] = relationship()
