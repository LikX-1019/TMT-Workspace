"""Department persistence boundary."""

from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.engine import ScalarResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.departments.models import Department


class DepartmentRepository:
    """Query and persistence operations for departments."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _active_statement() -> Select[Department]:
        return select(Department).where(
            Department.deleted_at.is_(None), Department.status == "active"
        )

    async def get_by_id(
        self, department_id: UUID, *, include_deleted: bool = False
    ) -> Department | None:
        statement = select(Department).where(Department.id == department_id)
        if not include_deleted:
            statement = statement.where(Department.deleted_at.is_(None))
        return await self._session.scalar(statement)

    async def get_by_code(self, code: str) -> Department | None:
        return await self._session.scalar(select(Department).where(Department.code == code))

    async def list_active(self) -> list[Department]:
        result = await self._session.scalars(
            self._active_statement().order_by(
                Department.sort.asc(), Department.name.asc(), Department.id.asc()
            )
        )
        return list(result)

    async def descendant_ids(self, department_id: UUID) -> list[UUID]:
        """Return active descendants using a PostgreSQL recursive CTE."""

        subtree = (
            select(Department.id)
            .where(Department.id == department_id, Department.deleted_at.is_(None))
            .cte(name="department_descendants", recursive=True)
        )
        subtree = subtree.union_all(
            select(Department.id)
            .join(subtree, Department.parent_id == subtree.c.id)
            .where(Department.deleted_at.is_(None))
        )
        statement = (
            select(subtree.c.id).where(subtree.c.id != department_id).order_by(subtree.c.id.asc())
        )
        result: ScalarResult[UUID] = await self._session.scalars(statement)
        return list(result)

    async def list_page(
        self,
        *,
        offset: int,
        limit: int,
        keyword: str | None = None,
        status: str | None = None,
        parent_id: UUID | None = None,
    ) -> tuple[list[Department], int]:
        """管理端分页列表：含 disabled、不含软删；sort/name 稳定排序。"""

        statement = select(Department).where(Department.deleted_at.is_(None))
        if keyword:
            pattern = f"%{keyword}%"
            statement = statement.where(
                Department.name.ilike(pattern) | Department.code.ilike(pattern)
            )
        if status is not None:
            statement = statement.where(Department.status == status)
        if parent_id is not None:
            statement = statement.where(Department.parent_id == parent_id)
        total = await self._session.scalar(select(func.count()).select_from(statement.subquery()))
        items = await self._session.scalars(
            statement.order_by(Department.sort.asc(), Department.name.asc(), Department.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(items), int(total or 0)

    async def create(self, department: Department) -> Department:
        self._session.add(department)
        await self._session.flush()
        return department
