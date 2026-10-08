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
from app.modules.users.schemas import (
    AccountStatusDTO,
    EmploymentStatusDTO,
    OrganizationSummary,
    UserCreate,
    UserListQuery,
    UserManagementRead,
    UserRead,
    UserUpdate,
)


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

    async def get_management_view(self, user_id: UUID) -> UserManagementRead:
        """详情视图：身份字段 + 主部门/主职位摘要，绝不含任何凭据信息。"""

        user = await self.get_active(user_id)
        primary_department = await self._repository.get_primary_department(user.id)
        primary_position = await self._repository.get_primary_position(user.id)
        return self._to_management_read(
            user,
            primary_department.department if primary_department else None,
            primary_position.position if primary_position else None,
        )

    async def list_users(self, query: UserListQuery) -> tuple[list[UserManagementRead], int]:
        """管理端分页列表：固定查询次数组装主部门/主职位，无行级 N+1。

        注意：department 过滤只是管理员的查询条件，不是数据范围强制；
        拥有 ``system:user:list`` 即可查询全量用户（Phase 2C 边界）。
        """

        order_column = {
            "created_at": User.created_at,
            "username": User.username,
            "employee_no": User.employee_no,
        }[query.order_by]
        items, total = await self._repository.list_page(
            offset=(query.page - 1) * query.page_size,
            limit=query.page_size,
            keyword=query.keyword,
            account_status=query.account_status.value if query.account_status else None,
            employment_status=(query.employment_status.value if query.employment_status else None),
            department_id=query.department_id,
            order_column=order_column,
            descending=query.order == "desc",
        )
        primary_departments = await self._repository.list_primary_departments(
            [user.id for user in items]
        )
        primary_positions = await self._repository.list_primary_positions(
            [user.id for user in items]
        )
        reads = [
            self._to_management_read(
                user,
                primary_departments.get(user.id),
                primary_positions.get(user.id),
            )
            for user in items
        ]
        return reads, total

    async def disable(self, user_id: UUID, *, operator_id: UUID) -> User:
        """禁用账号（account 层面），下一认证请求立即被拒。

        禁止操作者禁用自己：这会让当前管理员立即失去唯一操作入口。
        Phase 1B 的 ``get_current_user`` 逐请求校验账号状态，因此无需
        额外的会话吊销即可即时生效。
        """

        user = await self._require_other_user(user_id, operator_id, action="disable")
        user.account_status = AccountStatus.DISABLED
        await self._session.flush()
        return user

    async def enable(self, user_id: UUID) -> User:
        user = await self.get_active(user_id)
        user.account_status = AccountStatus.ACTIVE
        await self._session.flush()
        return user

    async def resign(self, user_id: UUID, *, operator_id: UUID) -> User:
        """员工离职（employment 层面），与账号禁用是两个概念。

        同样禁止操作者对自己执行：离职状态会让下一认证请求立即 401。
        """

        user = await self._require_other_user(user_id, operator_id, action="resign")
        user.employment_status = EmploymentStatus.RESIGNED
        await self._session.flush()
        return user

    async def update(
        self, user_id: UUID, payload: UserUpdate, *, operator_id: UUID | None = None
    ) -> User:
        user = await self.get_active(user_id)
        changes = payload.model_dump(exclude_unset=True)

        if operator_id is not None and user.id == operator_id:
            self._reject_self_lockout(payload=payload)

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

    async def _require_other_user(self, user_id: UUID, operator_id: UUID, *, action: str) -> User:
        """取目标用户并拒绝操作者对自己执行锁定类操作。"""

        if user_id == operator_id:
            raise ConflictError(f"You cannot {action} your own account.")
        return await self.get_active(user_id)

    @staticmethod
    def _reject_self_lockout(*, payload: UserUpdate) -> None:
        """PATCH 自我保护：不允许管理员通过 PATCH 把自己踢出系统。"""

        if payload.account_status is AccountStatusDTO.DISABLED:
            raise ConflictError("You cannot disable your own account.")
        if payload.employment_status is EmploymentStatusDTO.RESIGNED:
            raise ConflictError("You cannot resign your own account.")

    def _to_management_read(
        self,
        user: User,
        primary_department: object | None,
        primary_position: object | None,
    ) -> UserManagementRead:
        base = UserRead.model_validate(user)
        return UserManagementRead(
            **base.model_dump(),
            primary_department=(
                OrganizationSummary.model_validate(primary_department)
                if primary_department is not None
                else None
            ),
            primary_position=(
                OrganizationSummary.model_validate(primary_position)
                if primary_position is not None
                else None
            ),
        )

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
