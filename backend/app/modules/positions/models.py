"""Position persistence model."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PositionStatus(StrEnum):
    """Operational position lifecycle, independent of soft deletion."""

    ACTIVE = "active"
    DISABLED = "disabled"


class Position(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An organizational job; it never represents authorization."""

    __tablename__ = "positions"
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sort: Mapped[int] = mapped_column(default=0, nullable=False, server_default=text("0"))
    status: Mapped[PositionStatus] = mapped_column(
        Enum(
            PositionStatus,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
            create_constraint=True,
            name="status",
            validate_strings=True,
        ),
        default=PositionStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
