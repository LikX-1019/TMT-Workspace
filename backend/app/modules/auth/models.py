"""Authentication credential, refresh token, and login log persistence models.

Identity and authentication are deliberately separate aggregates: ``User``
models the employee, while ``LocalCredential`` models one authentication
provider (local password login). A user without a ``LocalCredential`` may
exist and would later authenticate exclusively through SSO providers.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db.base import Base, UUIDPrimaryKeyMixin, utc_now


class IpAddress(TypeDecorator[str]):
    """PostgreSQL INET storage that reads back as a plain string literal."""

    impl = INET
    cache_ok = True

    def process_result_value(self, value: object | None, dialect: object) -> str | None:
        del dialect
        return str(value) if value is not None else None


class LocalCredential(UUIDPrimaryKeyMixin, Base):
    """Local password-login credential; 1 : 0..1 with ``User``.

    Only the Argon2id hash is stored. Refresh tokens never live here.
    """

    __tablename__ = "local_credentials"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_local_credentials_user_id_users"),
        nullable=False,
        unique=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        server_default=text("false"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    """One issued refresh token inside a login session (token family).

    ``session_id`` groups the rotation chain of one login. Only the SHA-256
    hash of the opaque token is stored; rotation marks the old row revoked and
    links it to its replacement through ``replaced_by_id``.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_session_id", "session_id"),
        Index("ix_refresh_tokens_user_id_expires_at", "user_id", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_refresh_tokens_user_id_users"),
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "refresh_tokens.id",
            ondelete="RESTRICT",
            name="fk_refresh_tokens_replaced_by_id_refresh_tokens",
        ),
        nullable=True,
    )
    ip: Mapped[str | None] = mapped_column(IpAddress, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class LoginResult(StrEnum):
    """Terminal outcome of one login attempt."""

    SUCCESS = "success"
    FAILURE = "failure"
    RATE_LIMITED = "rate_limited"


class LoginLog(UUIDPrimaryKeyMixin, Base):
    """Append-only authentication attempt evidence.

    ``failure_reason`` is internal diagnostic data and never leaves the server.
    Passwords, access tokens, and refresh tokens are never recorded here.
    """

    __tablename__ = "login_logs"
    __table_args__ = (
        Index("ix_login_logs_username_created_at", "username", "created_at"),
        Index("ix_login_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_login_logs_ip_created_at", "ip", "created_at"),
    )

    username: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_login_logs_user_id_users"),
        nullable=True,
    )
    result: Mapped[LoginResult] = mapped_column(
        Enum(
            LoginResult,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
            create_constraint=True,
            name="result",
            validate_strings=True,
        ),
        nullable=False,
    )
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip: Mapped[str | None] = mapped_column(IpAddress, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
