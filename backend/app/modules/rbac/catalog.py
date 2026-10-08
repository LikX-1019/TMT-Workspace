"""Code-owned permission and system-role catalog.

The catalog is the development contract for what the platform *can* enforce:

- Every permission code the backend will ever check in a
  ``require_permission(...)`` dependency is declared here, once. The database
  mirrors this catalog through ``PermissionCatalogService.sync``; role-
  permission assignment is operational configuration, not a way to invent
  codes.
- Codes follow ``<namespace>:<resource>:<action>`` (lowercase, colon
  separated, no entity IDs). Adding a code here is a code review decision;
  removing one disables it in the database on the next sync (rows are never
  deleted so historical grants stay inspectable).
- System roles are likewise seeded from code so ``super_admin`` always exists
  with a stable meaning. ``super_admin`` is intentionally *not* wired to
  explicit permission rows: it resolves dynamically to every active
  permission (see AuthorizationService), so newly synced capabilities are
  available to break-glass administrators without a second write.

Phase 2A seeded only ``action`` kind codes for the ``system`` namespace.
Since Phase 3A, workspace access codes (``workspace:<code>:access``, kind
``workspace``) are derived deterministically from the code-owned workspace
registry (``app.modules.workspaces.registry``) and merged here, so
``sync-permissions`` sees them without a second hand-maintained list. The
``menu`` kind stays reserved; no ``data_scope`` permission codes exist
because data scope is role policy (``roles.data_scope_type``), not per-row
permission data. Workspace access codes are catalog data only in this phase:
no endpoint enforces them yet, and no system role receives them automatically.
"""

from dataclasses import dataclass

from app.modules.rbac.models import DataScopeType, PermissionKind
from app.modules.workspaces.registry import (
    WORKSPACE_REGISTRY,
    WorkspaceDefinition,
    workspace_access_permission_code,
)

SUPER_ADMIN_ROLE_CODE = "super_admin"
SYSTEM_ADMIN_ROLE_CODE = "system_admin"
SECURITY_AUDITOR_ROLE_CODE = "security_auditor"


@dataclass(frozen=True, slots=True)
class PermissionDefinition:
    """One catalog entry: exactly what one permission code means."""

    code: str
    name: str
    module: str
    kind: PermissionKind = PermissionKind.ACTION
    description: str | None = None


@dataclass(frozen=True, slots=True)
class SystemRoleDefinition:
    """One seeded system role.

    ``permission_codes`` lists the codes assigned at seed time. ``None``
    means dynamic full access (break-glass ``super_admin`` only).
    """

    code: str
    name: str
    description: str
    data_scope_type: DataScopeType
    sort: int
    permission_codes: tuple[str, ...] | None


def _user(action: str, name: str, description: str) -> PermissionDefinition:
    return PermissionDefinition(
        code=f"system:user:{action}", name=name, module="user", description=description
    )


def _department(action: str, name: str, description: str) -> PermissionDefinition:
    return PermissionDefinition(
        code=f"system:department:{action}", name=name, module="department", description=description
    )


def _position(action: str, name: str, description: str) -> PermissionDefinition:
    return PermissionDefinition(
        code=f"system:position:{action}", name=name, module="position", description=description
    )


def _role(action: str, name: str, description: str) -> PermissionDefinition:
    return PermissionDefinition(
        code=f"system:role:{action}", name=name, module="role", description=description
    )


def _workspace_access(definition: WorkspaceDefinition) -> PermissionDefinition:
    """由 Workspace Registry 确定性生成的 workspace access permission。"""

    return PermissionDefinition(
        code=workspace_access_permission_code(definition.code),
        name=f"访问{definition.name}",
        module="workspace",
        kind=PermissionKind.WORKSPACE,
        description=f"进入 {definition.name}（{definition.code}）的业务入口。",
    )


_SYSTEM_ACTION_PERMISSIONS: tuple[PermissionDefinition, ...] = (
    _user("list", "用户列表", "查看用户列表"),
    _user("view", "查看用户", "查看用户详情"),
    _user("create", "创建用户", "创建员工身份"),
    _user("update", "更新用户", "修改用户基本资料与组织关系"),
    _user("disable", "禁用用户", "禁用或恢复用户账号"),
    _department("list", "部门列表", "查看部门列表"),
    _department("view", "查看部门", "查看部门详情"),
    _department("create", "创建部门", "创建部门节点"),
    _department("update", "更新部门", "修改部门信息"),
    _department("move", "调整部门", "调整部门层级归属"),
    _department("disable", "禁用部门", "禁用或恢复部门"),
    _position("list", "职位列表", "查看职位列表"),
    _position("view", "查看职位", "查看职位详情"),
    _position("create", "创建职位", "创建职位定义"),
    _position("update", "更新职位", "修改职位信息"),
    _position("disable", "禁用职位", "禁用或恢复职位"),
    _role("list", "角色列表", "查看角色列表"),
    _role("view", "查看角色", "查看角色详情与权限构成"),
    _role("create", "创建角色", "创建新角色"),
    _role("update", "更新角色", "修改角色名称、描述与数据范围配置"),
    _role("disable", "禁用角色", "禁用或恢复角色"),
    _role("assign", "分配角色", "为用户分配或移除角色"),
    PermissionDefinition(
        code="system:permission:list",
        name="权限列表",
        module="permission",
        description="查看权限目录与权限定义",
    ),
)

# 完整目录 = action 权限 + 由 Workspace Registry 派生的 access 权限（单一数据源）。
SYSTEM_PERMISSIONS: tuple[PermissionDefinition, ...] = (
    *_SYSTEM_ACTION_PERMISSIONS,
    *(_workspace_access(definition) for definition in WORKSPACE_REGISTRY),
)

PERMISSION_ACTION_WORDS = ("list", "view")

# 权限码全集：require_permission 的 fail-fast 校验数据源（见 dependencies.py）。
CATALOG_PERMISSION_CODES: frozenset[str] = frozenset(
    definition.code for definition in SYSTEM_PERMISSIONS
)


class Permissions:
    """目录权限码的稳定常量表。

    业务代码必须引用这里的常量（``Permissions.USER_LIST``），禁止在路由里
    散落字符串字面量。单元测试保证本类属性与 ``SYSTEM_PERMISSIONS`` 完全
    一致，新增目录条目时漏加常量会直接在 CI 失败。
    """

    USER_LIST = "system:user:list"
    USER_VIEW = "system:user:view"
    USER_CREATE = "system:user:create"
    USER_UPDATE = "system:user:update"
    USER_DISABLE = "system:user:disable"

    DEPARTMENT_LIST = "system:department:list"
    DEPARTMENT_VIEW = "system:department:view"
    DEPARTMENT_CREATE = "system:department:create"
    DEPARTMENT_UPDATE = "system:department:update"
    DEPARTMENT_MOVE = "system:department:move"
    DEPARTMENT_DISABLE = "system:department:disable"

    POSITION_LIST = "system:position:list"
    POSITION_VIEW = "system:position:view"
    POSITION_CREATE = "system:position:create"
    POSITION_UPDATE = "system:position:update"
    POSITION_DISABLE = "system:position:disable"

    ROLE_LIST = "system:role:list"
    ROLE_VIEW = "system:role:view"
    ROLE_CREATE = "system:role:create"
    ROLE_UPDATE = "system:role:update"
    ROLE_DISABLE = "system:role:disable"
    ROLE_ASSIGN = "system:role:assign"

    PERMISSION_LIST = "system:permission:list"

    @classmethod
    def workspace_access(cls, workspace_code: str) -> str:
        """稳定派生 workspace access 权限码（Phase 3B enforcement 使用）。"""

        return workspace_access_permission_code(workspace_code)


SYSTEM_ROLES: tuple[SystemRoleDefinition, ...] = (
    SystemRoleDefinition(
        code=SUPER_ADMIN_ROLE_CODE,
        name="超级管理员",
        description="平台最终管理权限；动态拥有全部启用权限，用于系统初始化与应急。",
        data_scope_type=DataScopeType.ALL,
        sort=0,
        permission_codes=None,
    ),
    SystemRoleDefinition(
        code=SYSTEM_ADMIN_ROLE_CODE,
        name="系统管理员",
        description="日常平台管理；拥有当前系统管理权限，但不自动获得未来新增权限。",
        data_scope_type=DataScopeType.ALL,
        sort=10,
        permission_codes=tuple(definition.code for definition in _SYSTEM_ACTION_PERMISSIONS),
    ),
    SystemRoleDefinition(
        code=SECURITY_AUDITOR_ROLE_CODE,
        name="安全审计员",
        description="只读安全审查；仅保留 list/view 类权限。",
        data_scope_type=DataScopeType.ALL,
        sort=20,
        permission_codes=tuple(
            definition.code
            for definition in _SYSTEM_ACTION_PERMISSIONS
            if definition.code.rsplit(":", 1)[-1] in PERMISSION_ACTION_WORDS
        ),
    ),
)


def validate_catalog() -> list[str]:
    """Return a list of catalog contract violations (empty means valid).

    Checked by unit tests so a malformed entry fails in CI, never in a
    production sync.
    """

    problems: list[str] = []
    seen: set[str] = set()
    role_codes: set[str] = set()

    for definition in SYSTEM_PERMISSIONS:
        if definition.code in seen:
            problems.append(f"duplicate permission code: {definition.code}")
        seen.add(definition.code)

        segments = definition.code.split(":")
        if len(segments) != 3 or not all(
            segment and segment.replace("_", "").replace("-", "").isalnum() and segment.islower()
            for segment in segments
        ):
            problems.append(f"invalid permission code grammar: {definition.code}")
        if any(segment.isdigit() for segment in segments):
            problems.append(f"permission code must not encode entity ids: {definition.code}")
        if definition.kind not in (PermissionKind.ACTION, PermissionKind.WORKSPACE):
            problems.append(f"catalog declares action and workspace codes only: {definition.code}")
        if definition.kind is PermissionKind.ACTION and definition.module != segments[1]:
            problems.append(f"module does not match code resource: {definition.code}")
        if definition.kind is PermissionKind.WORKSPACE and (
            segments[0] != "workspace"
            or segments[2] != "access"
            or definition.module != "workspace"
        ):
            problems.append(f"workspace access code contract violated: {definition.code}")
        if not definition.name:
            problems.append(f"permission display name is required: {definition.code}")

    for role in SYSTEM_ROLES:
        if role.code in role_codes:
            problems.append(f"duplicate system role code: {role.code}")
        role_codes.add(role.code)
        if role.permission_codes is None and role.code != SUPER_ADMIN_ROLE_CODE:
            problems.append(f"only super_admin may use dynamic permissions: {role.code}")
        for code in role.permission_codes or ():
            if code not in seen:
                problems.append(f"role {role.code} references unknown permission: {code}")

    return problems
