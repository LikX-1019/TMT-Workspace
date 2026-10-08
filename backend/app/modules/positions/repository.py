"""Position persistence boundary."""

from uuid import UUID

from sqlalchemy import func, select
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

    async def list_page(
        self,
        *,
        offset: int,
        limit: int,
        keyword: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Position], int]:
        """管理端分页列表：含 disabled、不含软删；sort/name 稳定排序。"""

        statement = select(Position).where(Position.deleted_at.is_(None))
        if keyword:
            pattern = f"%{keyword}%"
            statement = statement.where(Position.name.ilike(pattern) | Position.code.ilike(pattern))
        if status is not None:
            statement = statement.where(Position.status == status)
        total = await self._session.scalar(select(func.count()).select_from(statement.subquery()))
        items = await self._session.scalars(
            statement.order_by(Position.sort.asc(), Position.name.asc(), Position.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(items), int(total or 0)

    async def create(self, position: Position) -> Position:
        self._session.add(position)
        await self._session.flush()
        return position
