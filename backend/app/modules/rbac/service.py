"""RBAC application services.

Three services with deliberately narrow contracts:

- ``RoleService``: role lifecycle rules (creation, code uniqueness, system
  role protection, soft delete).
- ``PermissionCatalogService``: synchronize the code-owned catalog into the
  database (explicit CLI operation, dry-run capable, never deletes rows).
- ``AuthorizationService``: resolve a user's roles and effective permission
  codes. Union-only semantics: disabled roles/permissions contribute
  nothing; duplicates collapse; there are no deny rules.

None of these services touch HTTP, workspaces, menus, or data-scope query
construction. Transaction boundaries follow the platform default: flush
here, commit in ``get_db_session`` (the CLI commits explicitly because it
owns the session).
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.base import utc_now
from app.modules.rbac.catalog import (
    SUPER_ADMIN_ROLE_CODE,
    SYSTEM_PERMISSIONS,
    SYSTEM_ROLES,
    PermissionDefinition,
    SystemRoleDefinition,
)
from app.modules.rbac.models import (
    DataScopeType,
    Permission,
    PermissionKind,
    PermissionStatus,
    Role,
    RolePermission,
    RoleStatus,
    UserRole,
)
from app.modules.rbac.repository import (
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRoleRepository,
)


@dataclass(slots=True)
class PermissionSetReplaceOutcome:
    """角色权限整体替换的逐项结果清单。"""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RoleCreateRequest:
    """Typed input for role creation; the display payload of Phase 2C APIs."""

    code: str
    name: str
    description: str | None = None
    data_scope_type: DataScopeType = DataScopeType.SELF
    sort: int = 0
    is_system: bool = False


class RoleService:
    """Enforce role lifecycle invariants."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._roles = RoleRepository(session)
        self._permissions = PermissionRepository(session)
        self._role_permissions = RolePermissionRepository(session)

    async def create_role(self, request: RoleCreateRequest) -> Role:
        """Create a role with a unique, lifecycle-stable code."""

        code = request.code.strip()
        if not code:
            raise ConflictError("Role code must not be empty.")
        if await self._roles.get_by_code(code, include_deleted=True) is not None:
            raise ConflictError(f"Role code '{code}' already exists.")

        role = Role(
            code=code,
            name=request.name,
            description=request.description,
            data_scope_type=request.data_scope_type,
            sort=request.sort,
            is_system=request.is_system,
            status=RoleStatus.ACTIVE,
        )
        return await self._roles.create(role)

    async def get_by_code(self, role_code: str, *, include_deleted: bool = False) -> Role | None:
        return await self._roles.get_by_code(role_code, include_deleted=include_deleted)

    async def get_active_by_id(self, role_id: UUID) -> Role:
        """按 id 取非软删角色；缺失即 404。"""

        role = await self._roles.get_by_id(role_id)
        if role is None:
            raise NotFoundError("Role not found.")
        return role

    async def list_active(self) -> list[Role]:
        return await self._roles.list_active()

    async def list_page(
        self, *, offset: int, limit: int, keyword: str | None = None
    ) -> tuple[list[Role], int]:
        """管理端分页列表（含 disabled、不含软删），返回 (items, total)。"""

        items = await self._roles.list_page(offset=offset, limit=limit, keyword=keyword)
        total = await self._roles.count(keyword=keyword)
        return items, total

    async def enable_role(self, role_id: UUID) -> Role:
        """恢复 disabled 角色；软删角色不可通过管理面复活（保持退役语义）。"""

        role = await self._roles.get_by_id(role_id)
        if role is None or role.deleted_at is not None:
            raise NotFoundError("Role not found.")
        role.status = RoleStatus.ACTIVE
        await self._session.flush()
        return role

    async def get_explicit_permission_codes(self, role_id: UUID) -> set[str]:
        """角色当前的显式权限码集合（super_admin 恒为空集：动态展开，无行）。"""

        role = await self.get_active_by_id(role_id)
        return await self._role_permissions_codes(role.id)

    async def replace_permissions(
        self, role_id: UUID, permission_codes: list[str]
    ) -> PermissionSetReplaceOutcome:
        """以目录权限码整体替换角色的显式权限集。

        契约：

        - 仅接受目录中存在且 active 的权限码；unknown/disabled 一律 422，
          客户端不能通过任何形式绕开目录；
        - ``super_admin`` 的能力来自动态展开，拒绝保存显式授权行（409）；
        - 增/删/不变在一个事务（请求事务）内完成，返回逐项清单。
        """

        role = await self.get_active_by_id(role_id)
        if role.is_system and role.code == SUPER_ADMIN_ROLE_CODE:
            raise ConflictError("System-managed role permissions cannot be edited.")

        desired: dict[str, Permission] = {}
        for code in dict.fromkeys(code.strip() for code in permission_codes):
            permission = await self._permissions.get_by_code(code)
            if permission is None:
                raise ValidationError(f"Unknown permission code: {code}")
            if permission.status is not PermissionStatus.ACTIVE:
                raise ValidationError(f"Permission is not active: {code}")
            desired[permission.code] = permission

        current_ids = await self._role_permissions.list_permission_ids_for_role(role.id)
        desired_ids = {permission.id for permission in desired.values()}
        all_codes = {
            permission.id: permission.code for permission in await self._permissions.list_all()
        }

        outcome = PermissionSetReplaceOutcome()
        for permission_id in current_ids - desired_ids:
            await self._role_permissions.remove(role.id, permission_id)
            outcome.removed.append(all_codes[permission_id])
        for code, permission in desired.items():
            if permission.id in current_ids:
                outcome.unchanged.append(code)
            else:
                await self._role_permissions.assign(role.id, permission.id)
                outcome.added.append(code)
        return outcome

    async def _role_permissions_codes(self, role_id: UUID) -> set[str]:
        statement = (
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
        )
        result = await self._session.scalars(statement)
        return set(result)

    async def update_profile(
        self,
        role_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        sort: int | None = None,
        data_scope_type: DataScopeType | None = None,
    ) -> Role:
        """Update display/policy metadata. ``code`` is immutable by design."""

        role = await self._roles.get_by_id(role_id)
        if role is None:
            raise NotFoundError("Role not found.")
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        if sort is not None:
            role.sort = sort
        if data_scope_type is not None:
            role.data_scope_type = data_scope_type
        await self._session.flush()
        return role

    async def disable_role(self, role_id: UUID) -> Role:
        """Disable a role so it stops contributing permissions.

        System roles are refused: disabling ``super_admin`` or
        ``system_admin`` silently is a platform-level hazard; retiring a
        system role is an explicit operator/data action instead.
        """

        role = await self._roles.get_by_id(role_id)
        if role is None:
            raise NotFoundError("Role not found.")
        if role.is_system:
            raise ConflictError("System roles cannot be disabled through ordinary management.")
        role.status = RoleStatus.DISABLED
        await self._session.flush()
        return role

    async def soft_delete_role(self, role_id: UUID, *, now: datetime | None = None) -> Role:
        """Soft-delete a role, preserving historical ``user_roles`` rows.

        System roles are never deletable. Disabled state is part of deletion:
        a deleted role must not resolve permissions even before any cache or
        transaction edge.
        """

        role = await self._roles.get_by_id(role_id)
        if role is None:
            raise NotFoundError("Role not found.")
        if role.is_system:
            raise ConflictError("System roles cannot be deleted.")
        role.status = RoleStatus.DISABLED
        role.deleted_at = now or utc_now()
        await self._session.flush()
        return role


@dataclass(slots=True)
class PermissionSyncReport:
    """Outcome of one catalog synchronization pass."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    reenabled: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    stale_disabled: list[str] = field(default_factory=list)
    roles_created: list[str] = field(default_factory=list)
    role_permissions_added: list[str] = field(default_factory=list)


class PermissionCatalogService:
    """Mirror the code-owned catalog into the database.

    Sync is an explicit operator action (``python -m app.cli sync-permissions``),
    never an application-startup side effect. Rules:

    - new catalog codes are inserted with stable generated ids;
    - existing rows keep their id/code; display fields follow the catalog;
    - codes removed from the catalog are disabled and reported stale — never
      deleted, so historical grants stay inspectable;
    - system roles are created once with ``is_system=true``; missing role-
      permission grants for seeded roles are added, never removed;
    - ``super_admin`` deliberately receives no explicit rows: its effective
      permissions resolve dynamically (see ``AuthorizationService``).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._roles = RoleRepository(session)
        self._permissions = PermissionRepository(session)
        self._role_permissions = RolePermissionRepository(session)
        self._permissions = PermissionRepository(session)
        self._user_roles = UserRoleRepository(session)
        self._role_permissions = RolePermissionRepository(session)

    async def sync(self, *, dry_run: bool = False) -> PermissionSyncReport:
        report = PermissionSyncReport()
        existing_by_code = {
            permission.code: permission for permission in await self._permissions.list_all()
        }
        catalog_by_code = {definition.code: definition for definition in SYSTEM_PERMISSIONS}

        for code, definition in catalog_by_code.items():
            existing = existing_by_code.get(code)
            if existing is None:
                report.created.append(code)
                if not dry_run:
                    await self._permissions.create(self._to_permission(definition))
                continue

            changed = (
                existing.name != definition.name
                or existing.kind != definition.kind
                or existing.module != definition.module
                or existing.description != definition.description
            )
            if changed:
                report.updated.append(code)
                if not dry_run:
                    existing.name = definition.name
                    existing.kind = definition.kind
                    existing.module = definition.module
                    existing.description = definition.description
            if existing.status != PermissionStatus.ACTIVE:
                report.reenabled.append(code)
                if not dry_run:
                    existing.status = PermissionStatus.ACTIVE
            if not changed and existing.status == PermissionStatus.ACTIVE:
                report.unchanged.append(code)

        for code, existing in existing_by_code.items():
            if code not in catalog_by_code and existing.status == PermissionStatus.ACTIVE:
                report.stale_disabled.append(code)
                if not dry_run:
                    existing.status = PermissionStatus.DISABLED

        await self._sync_system_roles(report, dry_run=dry_run)
        return report

    async def list_permissions(
        self,
        *,
        offset: int,
        limit: int,
        module: str | None = None,
        kind: PermissionKind | None = None,
        status: PermissionStatus | None = None,
        keyword: str | None = None,
    ) -> tuple[list[Permission], int]:
        """管理端只读列表：目录镜像可按 module/kind/status/keyword 过滤。"""

        items = await self._permissions.list_page(
            offset=offset,
            limit=limit,
            module=module,
            kind=kind,
            status=status,
            keyword=keyword,
        )
        total = await self._permissions.count(
            module=module, kind=kind, status=status, keyword=keyword
        )
        return items, total

    async def get_permission(self, permission_id: UUID) -> Permission:
        permission = await self._permissions.get_by_id(permission_id)
        if permission is None:
            raise NotFoundError("Permission not found.")
        return permission

    async def _sync_system_roles(self, report: PermissionSyncReport, *, dry_run: bool) -> None:
        active_permissions = {
            permission.code: permission for permission in await self._permissions.list_active()
        }

        for definition in SYSTEM_ROLES:
            role = await self._roles.get_by_code(definition.code, include_deleted=True)
            if role is None:
                report.roles_created.append(definition.code)
                if not dry_run:
                    role = await self._roles.create(self._to_role(definition))
            if role is None:
                continue

            if definition.permission_codes is None:
                continue  # dynamic full access; no rows by design
            for code in definition.permission_codes:
                permission = active_permissions.get(code)
                if permission is None:
                    continue  # stale or not-yet-synced code; nothing to grant
                grant = await self._role_permissions.get(role.id, permission.id)
                if grant is None:
                    report.role_permissions_added.append(f"{definition.code}:{code}")
                    if not dry_run:
                        await self._role_permissions.assign(role.id, permission.id)

    @staticmethod
    def _to_permission(definition: PermissionDefinition) -> Permission:
        return Permission(
            code=definition.code,
            name=definition.name,
            kind=definition.kind,
            module=definition.module,
            description=definition.description,
            status=PermissionStatus.ACTIVE,
        )

    @staticmethod
    def _to_role(definition: SystemRoleDefinition) -> Role:
        return Role(
            code=definition.code,
            name=definition.name,
            description=definition.description,
            data_scope_type=definition.data_scope_type,
            sort=definition.sort,
            is_system=True,
            status=RoleStatus.ACTIVE,
        )


class AuthorizationService:
    """Answer "which roles and permissions does this user hold?".

    Union-only resolution over active grants, roles, and permissions. The
    ``super_admin`` system role expands dynamically to every active
    permission code: the platform's break-glass capability is expressed as a
    normal role assignment (no username/id checks anywhere), and it stays
    correct when the catalog grows without rewriting assignment rows.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._roles = RoleRepository(session)
        self._permissions = PermissionRepository(session)
        self._role_permissions = RolePermissionRepository(session)
        self._permissions = PermissionRepository(session)
        self._user_roles = UserRoleRepository(session)
        self._role_permissions = RolePermissionRepository(session)

    async def get_roles(self, user_id: UUID) -> list[Role]:
        """Active, non-deleted roles of the user, display-ordered."""

        return await self._user_roles.list_active_roles_for_user(user_id)

    async def get_role_codes(self, user_id: UUID) -> list[str]:
        return [role.code for role in await self.get_roles(user_id)]

    async def get_effective_permission_codes(self, user_id: UUID) -> set[str]:
        """Union of all active permissions across the user's active roles."""

        roles = await self.get_roles(user_id)
        if not roles:
            return set()

        if any(_is_super_admin(role) for role in roles):
            return {permission.code for permission in await self._permissions.list_active()}

        role_ids = [role.id for role in roles]
        return await self._permissions.list_active_codes_by_role_ids(role_ids)

    async def has_permission(self, user_id: UUID, permission_code: str) -> bool:
        codes = await self.get_effective_permission_codes(user_id)
        return permission_code in codes

    async def list_user_grants(self, user_id: UUID) -> list[tuple[UserRole, Role]]:
        """用户的全部授予记录（grant + 角色行；不过滤状态，供管理端核对）。"""

        return await self._user_roles.list_grants_for_user(user_id)

    async def assign_role_by_id(
        self, user_id: UUID, role_id: UUID, *, assigned_by: UUID | None = None
    ) -> tuple[UUID, bool]:
        """按角色 id 幂等授予；仅 active、非软删角色可授予。"""

        role = await self._roles.get_by_id(role_id)
        if role is None:
            raise NotFoundError("Role not found.")
        if role.status != RoleStatus.ACTIVE or role.deleted_at is not None:
            raise ConflictError("Role is not active and cannot be assigned.")
        existing = await self._user_roles.get(user_id, role.id)
        await self._user_roles.assign_role(user_id, role.id, assigned_by=assigned_by)
        return role.id, existing is None

    async def remove_role_by_id(self, user_id: UUID, role_id: UUID) -> bool:
        """按角色 id 移除授予；角色行本身不受影响。"""

        role = await self._roles.get_by_id(role_id, include_deleted=True)
        if role is None:
            raise NotFoundError("Role not found.")
        return await self._user_roles.remove_role(user_id, role.id)

    async def assign_role(
        self, user_id: UUID, role_code: str, *, assigned_by: UUID | None = None
    ) -> tuple[UUID, bool]:
        """Assign a role by stable code; returns (role_id, newly_assigned).

        Only active, non-deleted roles can be granted. Duplicate assignment
        is idempotent rather than an error so bootstrap scripts stay safe.
        """

        role = await self._roles.get_by_code(role_code)
        if role is None:
            raise NotFoundError(f"Role '{role_code}' does not exist or is not active.")
        if role.status != RoleStatus.ACTIVE or role.deleted_at is not None:
            raise ConflictError(f"Role '{role_code}' is not active and cannot be assigned.")

        existing = await self._user_roles.get(user_id, role.id)
        if existing is not None:
            return role.id, False
        await self._user_roles.assign_role(user_id, role.id, assigned_by=assigned_by)
        return role.id, True

    async def remove_role(self, user_id: UUID, role_code: str) -> bool:
        role = await self._roles.get_by_code(role_code)
        if role is None:
            raise NotFoundError(f"Role '{role_code}' does not exist.")
        return await self._user_roles.remove_role(user_id, role.id)


def _is_super_admin(role: Role) -> bool:
    """The break-glass marker is the role itself, never a username or id."""

    return role.is_system and role.code == SUPER_ADMIN_ROLE_CODE
