"""Authentication aggregate persistence boundary.

Repositories here receive ``AsyncSession`` and never commit: the request
transaction commits in ``get_db_session`` unless a service documents an
explicit commit for security-critical failure paths.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import LocalCredential, LoginLog, RefreshToken


class LocalCredentialRepository:
    """Query and persistence operations for local password credentials."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(self, user_id: UUID) -> LocalCredential | None:
        statement = select(LocalCredential).where(LocalCredential.user_id == user_id)
        return await self._session.scalar(statement)

    async def create(self, credential: LocalCredential) -> LocalCredential:
        self._session.add(credential)
        await self._session.flush()
        return credential


class RefreshTokenRepository:
    """Refresh-token lineage queries; plaintext tokens never reach this layer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        """Lock one token row so concurrent rotation attempts serialize."""

        statement = (
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )
        return await self._session.scalar(statement)

    async def create(self, token: RefreshToken) -> RefreshToken:
        self._session.add(token)
        await self._session.flush()
        return token

    async def revoke_family(self, session_id: UUID, *, revoked_at: datetime) -> list[UUID]:
        """Revoke every non-revoked token of a session family.

        Returns the ids of the rows revoked so the caller can log/verify scope.
        """

        token_ids = await self._session.scalars(
            select(RefreshToken.id).where(
                RefreshToken.session_id == session_id,
                RefreshToken.revoked_at.is_(None),
            )
        )
        revoked_ids = list(token_ids)
        if revoked_ids:
            await self._session.execute(
                update(RefreshToken)
                .where(RefreshToken.id.in_(revoked_ids))
                .values(revoked_at=revoked_at)
            )
        return revoked_ids


class LoginLogRepository:
    """Append-only login attempt evidence writer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, log: LoginLog) -> LoginLog:
        self._session.add(log)
        await self._session.flush()
        return log

    async def list_by_username(self, username: str, *, limit: int = 20) -> list[LoginLog]:
        statement = (
            select(LoginLog)
            .where(LoginLog.username == username)
            .order_by(LoginLog.created_at.desc(), LoginLog.id.desc())
            .limit(limit)
        )
        result = await self._session.scalars(statement)
        return list(result)
