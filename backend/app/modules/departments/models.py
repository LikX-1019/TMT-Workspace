"""Department persistence model."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DepartmentStatus(StrEnum):
    """Operational department lifecycle, independent of soft deletion."""

    ACTIVE = "active"
    DISABLED = "disabled"


class Department(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A node in the company organization tree."""

    __tablename__ = "departments"
    __table_args__ = (
        CheckConstraint("parent_id IS NULL OR id <> parent_id", name="parent_not_self"),
        Index("ix_departments_deleted_at", "deleted_at"),
    )

    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "departments.id", ondelete="RESTRICT", name="fk_departments_parent_id_departments"
        ),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    leader_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_departments_leader_id_users"),
        nullable=True,
        index=True,
    )
    sort: Mapped[int] = mapped_column(default=0, nullable=False, server_default=text("0"))
    status: Mapped[DepartmentStatus] = mapped_column(
        Enum(
            DepartmentStatus,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
            create_constraint=True,
            name="status",
            validate_strings=True,
        ),
        default=DepartmentStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    parent: Mapped["Department | None"] = relationship(
        back_populates="children",
        remote_side="Department.id",
    )
    children: Mapped[list["Department"]] = relationship(back_populates="parent")
