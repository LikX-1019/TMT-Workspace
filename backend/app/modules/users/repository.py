"""User and organization assignment persistence boundary."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.departments.models import Department
from app.modules.positions.models import Position
from app.modules.users.models import User, UserDepartment, UserPosition


class UserRepository:
    """Query and persistence operations for employee identities and assignments."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_page(
        self,
        *,
        offset: int,
        limit: int,
        keyword: str | None = None,
        account_status: str | None = None,
        employment_status: str | None = None,
        department_id: UUID | None = None,
        order_column: Any = None,
        descending: bool = True,
    ) -> tuple[list[User], int]:
        """管理端分页列表：keyword/状态/部门过滤 + allowlist 排序。

        keyword 模糊匹配 username/name/email/employee_no；department_id 过滤
        是管理员主动的查询条件（不是数据范围强制）。返回 (items, total)。
        """

        statement = select(User).where(User.deleted_at.is_(None))
        if keyword:
            pattern = f"%{keyword}%"
            statement = statement.where(
                User.username.ilike(pattern)
                | User.name.ilike(pattern)
                | User.email.ilike(pattern)
                | User.employee_no.ilike(pattern)
            )
        if account_status is not None:
            statement = statement.where(User.account_status == account_status)
        if employment_status is not None:
            statement = statement.where(User.employment_status == employment_status)
        if department_id is not None:
            statement = statement.where(
                User.id.in_(
                    select(UserDepartment.user_id).where(
                        UserDepartment.department_id == department_id
                    )
                )
            )

        total = await self._session.scalar(select(func.count()).select_from(statement.subquery()))

        order_column = order_column if order_column is not None else User.created_at
        direction = order_column.desc() if descending else order_column.asc()
        items = await self._session.scalars(
            statement.order_by(direction, User.id.desc()).offset(offset).limit(limit)
        )
        return list(items), int(total or 0)

    async def list_primary_departments(self, user_ids: list[UUID]) -> dict[UUID, Department]:
        """一次 IN 查询取多个用户的主部门（活跃），避免行级 N+1。"""

        if not user_ids:
            return {}
        statement = (
            select(UserDepartment.user_id, Department)
            .join(Department, UserDepartment.department_id == Department.id)
            .where(
                UserDepartment.user_id.in_(user_ids),
                UserDepartment.is_primary.is_(True),
                Department.deleted_at.is_(None),
            )
        )
        rows = await self._session.execute(statement)
        return dict(rows.all())

    async def list_primary_positions(self, user_ids: list[UUID]) -> dict[UUID, Position]:
        """一次 IN 查询取多个用户的主职位（活跃），避免行级 N+1。"""

        if not user_ids:
            return {}
        statement = (
            select(UserPosition.user_id, Position)
            .join(Position, UserPosition.position_id == Position.id)
            .where(
                UserPosition.user_id.in_(user_ids),
                UserPosition.is_primary.is_(True),
                Position.deleted_at.is_(None),
            )
        )
        rows = await self._session.execute(statement)
        return dict(rows.all())

    async def get_by_id(self, user_id: UUID, *, include_deleted: bool = False) -> User | None:
        statement = select(User).where(User.id == user_id)
        if not include_deleted:
            statement = statement.where(User.deleted_at.is_(None))
        return await self._session.scalar(statement)

    async def get_by_username(self, username: str, *, include_deleted: bool = False) -> User | None:
        statement = select(User).where(User.username == username)
        if not include_deleted:
            statement = statement.where(User.deleted_at.is_(None))
        return await self._session.scalar(statement)

    async def get_any_by_username(self, username: str) -> User | None:
        return await self._session.scalar(select(User).where(User.username == username))

    async def get_by_employee_no(
        self, employee_no: str, *, include_deleted: bool = False
    ) -> User | None:
        statement = select(User).where(User.employee_no == employee_no)
        if not include_deleted:
            statement = statement.where(User.deleted_at.is_(None))
        return await self._session.scalar(statement)

    async def get_any_by_employee_no(self, employee_no: str) -> User | None:
        return await self._session.scalar(select(User).where(User.employee_no == employee_no))

    async def get_with_assignments(self, user_id: UUID) -> User | None:
        statement = (
            select(User)
            .where(User.id == user_id, User.deleted_at.is_(None))
            .options(
                selectinload(User.department_assignments),
                selectinload(User.position_assignments),
            )
        )
        return await self._session.scalar(statement)

    async def create(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_department_assignment(
        self, user_id: UUID, department_id: UUID
    ) -> UserDepartment | None:
        statement = select(UserDepartment).where(
            UserDepartment.user_id == user_id,
            UserDepartment.department_id == department_id,
        )
        return await self._session.scalar(statement)

    async def list_departments(self, user_id: UUID) -> list[UserDepartment]:
        result = await self._session.scalars(
            select(UserDepartment)
            .join(Department, UserDepartment.department_id == Department.id)
            .where(UserDepartment.user_id == user_id, Department.deleted_at.is_(None))
            .order_by(
                UserDepartment.is_primary.desc(),
                Department.sort.asc(),
                Department.name.asc(),
                Department.id.asc(),
            )
        )
        return list(result)

    async def get_primary_department(self, user_id: UUID) -> UserDepartment | None:
        """Return the active primary department assignment with its department."""

        statement = (
            select(UserDepartment)
            .options(selectinload(UserDepartment.department))
            .join(Department, UserDepartment.department_id == Department.id)
            .where(
                UserDepartment.user_id == user_id,
                UserDepartment.is_primary.is_(True),
                Department.deleted_at.is_(None),
            )
        )
        return await self._session.scalar(statement)

    async def clear_primary_departments(
        self, user_id: UUID, *, excluding_department_id: UUID | None
    ) -> None:
        statement = select(UserDepartment).where(
            UserDepartment.user_id == user_id,
            UserDepartment.is_primary.is_(True),
        )
        if excluding_department_id is not None:
            statement = statement.where(UserDepartment.department_id != excluding_department_id)
        assignments = await self._session.scalars(statement)
        for assignment in assignments:
            assignment.is_primary = False

    async def create_department_assignment(self, assignment: UserDepartment) -> UserDepartment:
        self._session.add(assignment)
        await self._session.flush()
        return assignment

    async def get_position_assignment(
        self, user_id: UUID, position_id: UUID
    ) -> UserPosition | None:
        statement = select(UserPosition).where(
            UserPosition.user_id == user_id,
            UserPosition.position_id == position_id,
        )
        return await self._session.scalar(statement)

    async def list_positions(self, user_id: UUID) -> list[UserPosition]:
        result = await self._session.scalars(
            select(UserPosition)
            .join(Position, UserPosition.position_id == Position.id)
            .where(UserPosition.user_id == user_id, Position.deleted_at.is_(None))
            .order_by(
                UserPosition.is_primary.desc(),
                Position.sort.asc(),
                Position.name.asc(),
                Position.id.asc(),
            )
        )
        return list(result)

    async def get_primary_position(self, user_id: UUID) -> UserPosition | None:
        """Return the active primary position assignment with its position."""

        statement = (
            select(UserPosition)
            .options(selectinload(UserPosition.position))
            .join(Position, UserPosition.position_id == Position.id)
            .where(
                UserPosition.user_id == user_id,
                UserPosition.is_primary.is_(True),
                Position.deleted_at.is_(None),
            )
        )
        return await self._session.scalar(statement)

    async def clear_primary_positions(
        self, user_id: UUID, *, excluding_position_id: UUID | None
    ) -> None:
        statement = select(UserPosition).where(
            UserPosition.user_id == user_id,
            UserPosition.is_primary.is_(True),
        )
        if excluding_position_id is not None:
            statement = statement.where(UserPosition.position_id != excluding_position_id)
        assignments = await self._session.scalars(statement)
        for assignment in assignments:
            assignment.is_primary = False

    async def create_position_assignment(self, assignment: UserPosition) -> UserPosition:
        self._session.add(assignment)
        await self._session.flush()
        return assignment
