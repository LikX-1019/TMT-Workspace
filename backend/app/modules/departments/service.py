"""Department domain rules and orchestration."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.base import utc_now
from app.modules.departments.models import Department, DepartmentStatus
from app.modules.departments.repository import DepartmentRepository
from app.modules.departments.schemas import (
    DepartmentCreate,
    DepartmentRead,
    DepartmentTreeNode,
    DepartmentUpdate,
)
from app.modules.users.repository import UserRepository


class DepartmentService:
    """Enforce department invariants before persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = DepartmentRepository(session)
        self._users = UserRepository(session)

    async def create(self, payload: DepartmentCreate) -> Department:
        code = self._normalize_code(payload.code)
        await self._ensure_code_available(code)
        await self._validate_parent(payload.parent_id)
        await self._validate_leader(payload.leader_id)

        department = Department(
            name=payload.name.strip(),
            code=code,
            parent_id=payload.parent_id,
            leader_id=payload.leader_id,
            sort=payload.sort,
            status=DepartmentStatus(payload.status.value),
        )
        return await self._repository.create(department)

    async def get_active(self, department_id: UUID) -> Department:
        department = await self._repository.get_by_id(department_id)
        if department is None:
            raise NotFoundError("Department not found.")
        return department

    async def get_active_by_code(self, code: str) -> Department:
        department = await self._repository.get_by_code(self._normalize_code(code))
        if (
            department is None
            or department.deleted_at is not None
            or department.status != DepartmentStatus.ACTIVE
        ):
            raise NotFoundError("Department not found.")
        return department

    async def update(self, department_id: UUID, payload: DepartmentUpdate) -> Department:
        department = await self.get_active(department_id)
        changes = payload.model_dump(exclude_unset=True)

        if "code" in changes:
            normalized_code = self._normalize_code(changes["code"])
            existing = await self._repository.get_by_code(normalized_code)
            if existing is not None and existing.id != department.id:
                raise ConflictError("Department code already exists.")
            department.code = normalized_code

        if "parent_id" in changes:
            await self._validate_move(department, changes["parent_id"])
            department.parent_id = changes["parent_id"]

        if "leader_id" in changes:
            await self._validate_leader(changes["leader_id"], excluding_user_id=None)
            department.leader_id = changes["leader_id"]

        if "name" in changes:
            department.name = changes["name"].strip()
        if "sort" in changes:
            department.sort = changes["sort"]
        if "status" in changes:
            department.status = DepartmentStatus(changes["status"].value)

        await self._session.flush()
        return department

    async def move(self, department_id: UUID, parent_id: UUID | None) -> Department:
        department = await self.get_active(department_id)
        await self._validate_move(department, parent_id)
        department.parent_id = parent_id
        await self._session.flush()
        return department

    async def disable(self, department_id: UUID) -> Department:
        department = await self.get_active(department_id)
        department.status = DepartmentStatus.DISABLED
        await self._session.flush()
        return department

    async def soft_delete(self, department_id: UUID) -> Department:
        department = await self.get_active(department_id)
        department.deleted_at = utc_now()
        await self._session.flush()
        return department

    async def tree(self) -> list[DepartmentTreeNode]:
        departments = await self._repository.list_active()
        department_reads = [DepartmentRead.model_validate(department) for department in departments]
        nodes = {
            read.id: DepartmentTreeNode(**read.model_dump(), children=[])
            for read in department_reads
        }
        roots: list[DepartmentTreeNode] = []
        for department in departments:
            node = nodes[department.id]
            if department.parent_id is not None and department.parent_id in nodes:
                nodes[department.parent_id].children.append(node)
            else:
                roots.append(node)
        return roots

    async def descendant_ids(self, department_id: UUID) -> list[UUID]:
        await self.get_active(department_id)
        return await self._repository.descendant_ids(department_id)

    async def _ensure_code_available(self, code: str) -> None:
        if await self._repository.get_by_code(code) is not None:
            raise ConflictError("Department code already exists.")

    async def _validate_parent(self, parent_id: UUID | None) -> None:
        if parent_id is None:
            return
        parent = await self._repository.get_by_id(parent_id)
        if parent is None:
            raise NotFoundError("Parent department not found.")

    async def _validate_move(self, department: Department, parent_id: UUID | None) -> None:
        if parent_id is None:
            return
        if parent_id == department.id:
            raise ValidationError("A department cannot be its own parent.")

        await self._validate_parent(parent_id)
        descendant_ids = await self._repository.descendant_ids(department.id)
        if parent_id in descendant_ids:
            raise ValidationError("A department cannot be moved under one of its descendants.")

    async def _validate_leader(
        self, leader_id: UUID | None, *, excluding_user_id: UUID | None = None
    ) -> None:
        if leader_id is None:
            return
        leader = await self._users.get_by_id(leader_id)
        if leader is None or (excluding_user_id is not None and leader.id == excluding_user_id):
            raise NotFoundError("Department leader not found.")

    @staticmethod
    def _normalize_code(code: str) -> str:
        normalized = code.strip().lower()
        if not normalized:
            raise ValidationError("Department code is required.")
        return normalized
