"""User identity and organization assignment domain rules."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.departments.repository import DepartmentRepository
from app.modules.positions.repository import PositionRepository
from app.modules.users.models import (
    AccountStatus,
    EmploymentStatus,
    User,
    UserDepartment,
    UserPosition,
)
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate, UserUpdate


class UserService:
    """Enforce employee identity and assignment invariants."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = UserRepository(session)
        self._departments = DepartmentRepository(session)
        self._positions = PositionRepository(session)

    async def create(self, payload: UserCreate) -> User:
        employee_no = payload.employee_no.strip()
        username = self._normalize_username(payload.username)
        email = self._normalize_email(payload.email)
        mobile = self._normalize_mobile(payload.mobile)
        await self._ensure_identifiers_available(
            employee_no=employee_no,
            username=username,
            email=email,
            mobile=mobile,
        )
        await self._validate_supervisor(payload.primary_supervisor_id, user_id=None)

        user = User(
            employee_no=employee_no,
            username=username,
            name=payload.name.strip(),
            email=email,
            mobile=mobile,
            avatar_url=payload.avatar_url,
            employment_status=EmploymentStatus(payload.employment_status.value),
            account_status=AccountStatus(payload.account_status.value),
            primary_supervisor_id=payload.primary_supervisor_id,
        )
        return await self._create_guarded(user)

    async def get_active(self, user_id: UUID) -> User:
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return user

    async def update(self, user_id: UUID, payload: UserUpdate) -> User:
        user = await self.get_active(user_id)
        changes = payload.model_dump(exclude_unset=True)

        employee_no = user.employee_no
        username = user.username
        email = user.email
        mobile = user.mobile
        if "employee_no" in changes:
            employee_no = changes["employee_no"].strip()
        if "username" in changes:
            username = self._normalize_username(changes["username"])
        if "email" in changes:
            email = self._normalize_email(changes["email"])
        if "mobile" in changes:
            mobile = self._normalize_mobile(changes["mobile"])

        await self._ensure_identifiers_available(
            employee_no=employee_no,
            username=username,
            email=email,
            mobile=mobile,
            excluding_user_id=user.id,
        )

        if "primary_supervisor_id" in changes:
            await self._validate_supervisor(changes["primary_supervisor_id"], user_id=user.id)
            user.primary_supervisor_id = changes["primary_supervisor_id"]

        user.employee_no = employee_no
        user.username = username
        user.email = email
        user.mobile = mobile
        if "name" in changes:
            user.name = changes["name"].strip()
        if "avatar_url" in changes:
            user.avatar_url = changes["avatar_url"]
        if "employment_status" in changes:
            user.employment_status = EmploymentStatus(changes["employment_status"].value)
        if "account_status" in changes:
            user.account_status = AccountStatus(changes["account_status"].value)

        await self._session.flush()
        return user

    async def soft_delete(self, user_id: UUID) -> User:
        user = await self.get_active(user_id)
        user.deleted_at = self._now()
        await self._session.flush()
        return user

    async def assign_department(
        self, user_id: UUID, department_id: UUID, *, is_primary: bool
    ) -> UserDepartment:
        user = await self.get_active(user_id)
        department = await self._departments.get_by_id(department_id)
        if department is None:
            raise NotFoundError("Department not found.")

        assignment = await self._repository.get_department_assignment(user_id, department_id)
        if assignment is not None:
            raise ConflictError("User department assignment already exists.")

        is_new_assignment = assignment is None
        if assignment is None:
            assignment = UserDepartment(
                user_id=user.id, department_id=department.id, is_primary=is_primary
            )
        if is_primary:
            await self._repository.clear_primary_departments(
                user.id, excluding_department_id=department.id
            )
            assignment.is_primary = True
        else:
            assignment.is_primary = is_primary

        if is_new_assignment:
            return await self._create_department_assignment_guarded(assignment)
        await self._session.flush()
        return assignment

    async def list_departments(self, user_id: UUID) -> list[UserDepartment]:
        await self.get_active(user_id)
        return await self._repository.list_departments(user_id)

    async def assign_position(
        self, user_id: UUID, position_id: UUID, *, is_primary: bool
    ) -> UserPosition:
        user = await self.get_active(user_id)
        position = await self._positions.get_by_id(position_id)
        if position is None:
            raise NotFoundError("Position not found.")

        assignment = await self._repository.get_position_assignment(user_id, position_id)
        if assignment is not None:
            raise ConflictError("User position assignment already exists.")

        is_new_assignment = assignment is None
        if assignment is None:
            assignment = UserPosition(
                user_id=user.id, position_id=position.id, is_primary=is_primary
            )
        if is_primary:
            await self._repository.clear_primary_positions(
                user.id, excluding_position_id=position.id
            )
            assignment.is_primary = True
        else:
            assignment.is_primary = is_primary

        if is_new_assignment:
            return await self._create_position_assignment_guarded(assignment)
        await self._session.flush()
        return assignment

    async def list_positions(self, user_id: UUID) -> list[UserPosition]:
        await self.get_active(user_id)
        return await self._repository.list_positions(user_id)

    async def _ensure_identifiers_available(
        self,
        *,
        employee_no: str,
        username: str,
        email: str | None,
        mobile: str | None,
        excluding_user_id: UUID | None = None,
    ) -> None:
        checks = [
            (
                "Employee number already exists.",
                await self._repository.get_any_by_employee_no(employee_no),
            ),
            ("Username already exists.", await self._repository.get_any_by_username(username)),
        ]
        for message, existing in checks:
            if existing is not None and existing.id != excluding_user_id:
                raise ConflictError(message)

        if email is not None:
            statement_user = await self._find_by_email(email)
            if statement_user is not None and statement_user.id != excluding_user_id:
                raise ConflictError("Email already exists.")
        if mobile is not None:
            statement_user = await self._find_by_mobile(mobile)
            if statement_user is not None and statement_user.id != excluding_user_id:
                raise ConflictError("Mobile number already exists.")

    async def _find_by_email(self, email: str) -> User | None:
        from sqlalchemy import select

        return await self._session.scalar(select(User).where(User.email == email))

    async def _find_by_mobile(self, mobile: str) -> User | None:
        from sqlalchemy import select

        return await self._session.scalar(select(User).where(User.mobile == mobile))

    async def _validate_supervisor(
        self, supervisor_id: UUID | None, *, user_id: UUID | None
    ) -> None:
        if supervisor_id is None:
            return
        if supervisor_id == user_id:
            raise ValidationError("A user cannot be their own supervisor.")
        supervisor = await self._repository.get_by_id(supervisor_id)
        if supervisor is None:
            raise NotFoundError("Supervisor not found.")

    async def _create_guarded(self, user: User) -> User:
        try:
            return await self._repository.create(user)
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError("User identifier already exists.") from error

    async def _create_department_assignment_guarded(
        self, assignment: UserDepartment
    ) -> UserDepartment:
        try:
            return await self._repository.create_department_assignment(assignment)
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError(
                "User department assignment conflicts with existing state."
            ) from error

    async def _create_position_assignment_guarded(self, assignment: UserPosition) -> UserPosition:
        try:
            return await self._repository.create_position_assignment(assignment)
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError(
                "User position assignment conflicts with existing state."
            ) from error

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _normalize_username(username: str) -> str:
        normalized = username.strip().lower()
        if not normalized:
            raise ValidationError("Username is required.")
        return normalized

    @staticmethod
    def _normalize_email(email: str | None) -> str | None:
        return email.strip().lower() if email is not None else None

    @staticmethod
    def _normalize_mobile(mobile: str | None) -> str | None:
        return mobile.strip() if mobile is not None else None
