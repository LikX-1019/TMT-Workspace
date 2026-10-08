"""RBAC persistence boundary.

Repositories receive ``AsyncSession`` and never commit. Resolution queries
are set-based joins (no N+1): effective permissions are resolved with a
single statement, and super-admin expansion is a single scan of active
permissions.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rbac.models import (
    Permission,
    PermissionKind,
    PermissionStatus,
    Role,
    RolePermission,
    RoleStatus,
    UserRole,
)


class RoleRepository:
    """Role lifecycle queries. Codes are unique across the full lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, role_id: UUID, *, include_deleted: bool = False) -> Role | None:
        statement = select(Role).where(Role.id == role_id)
        if not include_deleted:
            statement = statement.where(Role.deleted_at.is_(None))
        return await self._session.scalar(statement)

    async def get_by_code(self, role_code: str, *, include_deleted: bool = False) -> Role | None:
        """Return the role with this stable code, including soft-deleted rows
        when requested, so callers can distinguish "absent" from "retired"."""

        statement = select(Role).where(Role.code == role_code)
        if not include_deleted:
            statement = statement.where(Role.deleted_at.is_(None))
        return await self._session.scalar(statement)

    async def list_active(self) -> list[Role]:
        statement = (
            select(Role)
            .where(Role.deleted_at.is_(None), Role.status == RoleStatus.ACTIVE)
            .order_by(Role.sort, Role.code)
        )
        result = await self._session.scalars(statement)
        return list(result)

    async def list_page(self, *, offset: int, limit: int, keyword: str | None = None) -> list[Role]:
        """管理端分页列表：含 disabled 角色（不含软删），稳定排序。"""

        statement = select(Role).where(Role.deleted_at.is_(None))
        if keyword:
            statement = statement.where(
                Role.code.ilike(f"%{keyword}%") | Role.name.ilike(f"%{keyword}%")
            )
        statement = statement.order_by(Role.sort.asc(), Role.code.asc()).offset(offset).limit(limit)
        result = await self._session.scalars(statement)
        return list(result)

    async def count(self, *, keyword: str | None = None) -> int:
        statement = select(func.count()).select_from(Role).where(Role.deleted_at.is_(None))
        if keyword:
            statement = statement.where(
                Role.code.ilike(f"%{keyword}%") | Role.name.ilike(f"%{keyword}%")
            )
        total = await self._session.scalar(statement)
        return int(total or 0)

    async def create(self, role: Role) -> Role:
        self._session.add(role)
        await self._session.flush()
        return role


class PermissionRepository:
    """Permission mirror-of-catalog queries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_code(self, permission_code: str) -> Permission | None:
        statement = select(Permission).where(Permission.code == permission_code)
        return await self._session.scalar(statement)

    async def list_all(self) -> list[Permission]:
        statement = select(Permission).order_by(Permission.code)
        result = await self._session.scalars(statement)
        return list(result)

    async def get_by_id(self, permission_id: UUID) -> Permission | None:
        return await self._session.scalar(select(Permission).where(Permission.id == permission_id))

    async def list_active(self) -> list[Permission]:
        statement = (
            select(Permission)
            .where(Permission.status == PermissionStatus.ACTIVE)
            .order_by(Permission.code)
        )
        result = await self._session.scalars(statement)
        return list(result)

    async def list_page(
        self,
        *,
        offset: int,
        limit: int,
        module: str | None = None,
        kind: PermissionKind | None = None,
        status: PermissionStatus | None = None,
        keyword: str | None = None,
    ) -> list[Permission]:
        """管理端只读列表：module/kind/status/keyword 过滤，code 稳定排序。"""

        statement = select(Permission)
        if module is not None:
            statement = statement.where(Permission.module == module)
        if kind is not None:
            statement = statement.where(Permission.kind == kind)
        if status is not None:
            statement = statement.where(Permission.status == status)
        if keyword:
            statement = statement.where(
                Permission.code.ilike(f"%{keyword}%") | Permission.name.ilike(f"%{keyword}%")
            )
        statement = statement.order_by(Permission.code.asc()).offset(offset).limit(limit)
        result = await self._session.scalars(statement)
        return list(result)

    async def count(
        self,
        *,
        module: str | None = None,
        kind: PermissionKind | None = None,
        status: PermissionStatus | None = None,
        keyword: str | None = None,
    ) -> int:
        statement = select(func.count()).select_from(Permission)
        if module is not None:
            statement = statement.where(Permission.module == module)
        if kind is not None:
            statement = statement.where(Permission.kind == kind)
        if status is not None:
            statement = statement.where(Permission.status == status)
        if keyword:
            statement = statement.where(
                Permission.code.ilike(f"%{keyword}%") | Permission.name.ilike(f"%{keyword}%")
            )
        total = await self._session.scalar(statement)
        return int(total or 0)

    async def list_active_codes_by_role_ids(self, role_ids: list[UUID]) -> set[str]:
        """Effective permission codes for the given roles in one joined query.

        Only active roles, active grants, and active permissions contribute.
        Set semantics deduplicate codes shared across roles.
        """

        if not role_ids:
            return set()
        statement = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .where(
                Role.id.in_(role_ids),
                Role.status == RoleStatus.ACTIVE,
                Role.deleted_at.is_(None),
                Permission.status == PermissionStatus.ACTIVE,
            )
            .distinct()
        )
        result = await self._session.scalars(statement)
        return set(result)

    async def create(self, permission: Permission) -> Permission:
        self._session.add(permission)
        await self._session.flush()
        return permission


class UserRoleRepository:
    """User-to-role grant persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID, role_id: UUID) -> UserRole | None:
        statement = select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == role_id,
        )
        return await self._session.scalar(statement)

    async def list_active_roles_for_user(self, user_id: UUID) -> list[Role]:
        """Active, non-deleted roles of one user, ordered for stable display."""

        statement = (
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == user_id,
                Role.status == RoleStatus.ACTIVE,
                Role.deleted_at.is_(None),
            )
            .order_by(Role.sort, Role.code)
        )
        result = await self._session.scalars(statement)
        return list(result)

    async def assign_role(
        self, user_id: UUID, role_id: UUID, *, assigned_by: UUID | None = None
    ) -> UserRole:
        """Idempotently grant one role; the unique constraint is the backstop."""

        existing = await self.get(user_id, role_id)
        if existing is not None:
            return existing
        grant = UserRole(user_id=user_id, role_id=role_id, assigned_by=assigned_by)
        self._session.add(grant)
        await self._session.flush()
        return grant

    async def list_grants_for_user(self, user_id: UUID) -> list[tuple[UserRole, Role]]:
        """用户的全部角色授予记录（grant + 角色行；不过滤状态，管理视角看全量）。"""

        statement = (
            select(UserRole, Role)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
            .order_by(UserRole.assigned_at.asc(), Role.code.asc())
        )
        rows = await self._session.execute(statement)
        return [(grant, role) for grant, role in rows.all()]

    async def remove_role(self, user_id: UUID, role_id: UUID) -> bool:
        """Remove one grant. Historical rows are deleted only by this explicit
        management action; the role itself stays soft-deletable."""

        grant = await self.get(user_id, role_id)
        if grant is None:
            return False
        await self._session.delete(grant)
        await self._session.flush()
        return True


class RolePermissionRepository:
    """Role-to-permission grant persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, role_id: UUID, permission_id: UUID) -> RolePermission | None:
        statement = select(RolePermission).where(
            RolePermission.role_id == role_id,
            RolePermission.permission_id == permission_id,
        )
        return await self._session.scalar(statement)

    async def assign(self, role_id: UUID, permission_id: UUID) -> RolePermission:
        """Idempotently grant one permission to one role."""

        existing = await self.get(role_id, permission_id)
        if existing is not None:
            return existing
        grant = RolePermission(role_id=role_id, permission_id=permission_id)
        self._session.add(grant)
        await self._session.flush()
        return grant

    async def remove(self, role_id: UUID, permission_id: UUID) -> bool:
        grant = await self.get(role_id, permission_id)
        if grant is None:
            return False
        await self._session.delete(grant)
        await self._session.flush()
        return True

    async def list_permission_ids_for_role(self, role_id: UUID) -> set[UUID]:
        statement = select(RolePermission.permission_id).where(RolePermission.role_id == role_id)
        result = await self._session.scalars(statement)
        return set(result)
