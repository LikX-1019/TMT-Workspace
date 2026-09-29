"""Position persistence boundary."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.positions.models import Position


class PositionRepository:
    """Query and persistence operations for organizational jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, position_id: UUID, *, include_deleted: bool = False
    ) -> Position | None:
        statement = select(Position).where(Position.id == position_id)
        if not include_deleted:
            statement = statement.where(Position.deleted_at.is_(None))
        return await self._session.scalar(statement)

    async def get_by_code(self, code: str) -> Position | None:
        return await self._session.scalar(select(Position).where(Position.code == code))

    async def create(self, position: Position) -> Position:
        self._session.add(position)
        await self._session.flush()
        return position
