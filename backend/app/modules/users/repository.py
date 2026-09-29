"""User and organization assignment persistence boundary."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.departments.models import Department
from app.modules.positions.models import Position
from app.modules.users.models import User, UserDepartment, UserPosition


class UserRepository:
    """Query and persistence operations for employee identities and assignments."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
