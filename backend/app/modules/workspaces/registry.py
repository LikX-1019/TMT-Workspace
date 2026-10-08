"""Code-owned workspace registry.

Workspaces are software entry points, not free-form database rows: a real
workspace also depends on a frontend entry, route registry, menu components,
backend capabilities, and permission codes. Therefore the set of workspaces
that *may exist* is owned by this registry (mirroring the permission catalog
approach); the database only mirrors definitions and stores operational state
(status, display metadata, associations).

Contracts:

- ``code`` is a stable software identifier. Once a workspace code ships in
  permission codes, menus, role grants, or external integrations, renaming it
  is prohibitively expensive — treat registry changes as code review decisions.
- Workspace access permissions are derived deterministically from this
  registry (``workspace:<code>:access``) and merged into the permission
  catalog in ``app.modules.rbac.catalog``. There is exactly one access
  permission per registered workspace, of kind ``workspace``.
- This module must stay dependency-free (no rbac/db imports) so the rbac
  catalog can consume it without circular imports.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkspaceDefinition:
    """One registered workspace.

    ``code`` is immutable identity; the remaining fields are registry-seeded
    display metadata (the database row keeps its own configurable status and
    operators may adjust display fields through future management features).
    """

    code: str
    name: str
    description: str
    icon: str | None = None
    home_path: str | None = None
    sort: int = 0


def workspace_access_permission_code(workspace_code: str) -> str:
    """Deterministic workspace access permission code for one workspace."""

    return f"workspace:{workspace_code}:access"


# 当前真正规划的业务 Workspace（与 frontend/src/workspaces/ 的 canonical
# 目录一一对应）。Home/Public/Supply Chain 等尚无前端入口与产品消费者，
# 在它们真实立项前不得预先注册；System Management 是平台能力，永远不是
# 业务 Workspace（见 AGENTS.md 与 ARCHITECTURE.md 的边界规则）。
WORKSPACE_REGISTRY: tuple[WorkspaceDefinition, ...] = (
    WorkspaceDefinition(
        code="operation",
        name="运营中心",
        description="运营与业务协作工作区。",
        sort=10,
    ),
    WorkspaceDefinition(
        code="product",
        name="产品中心",
        description="产品管理工作区。",
        sort=20,
    ),
    WorkspaceDefinition(
        code="procurement",
        name="采购中心",
        description="采购与供应商协同工作区。",
        sort=30,
    ),
    WorkspaceDefinition(
        code="warehouse",
        name="仓储中心",
        description="仓储与库存作业工作区。",
        sort=40,
    ),
    WorkspaceDefinition(
        code="customer-service",
        name="客服中心",
        description="客户服务工作区。",
        sort=50,
    ),
    WorkspaceDefinition(
        code="finance",
        name="财务中心",
        description="财务管理工作区。",
        sort=60,
    ),
    WorkspaceDefinition(
        code="hr",
        name="人力资源中心",
        description="人力资源工作区。",
        sort=70,
    ),
    WorkspaceDefinition(
        code="tech",
        name="技术中心",
        description="技术研发工作区。",
        sort=80,
    ),
)


def validate_workspace_registry() -> list[str]:
    """Return registry contract violations (empty list means valid).

    Checked by unit tests so a malformed workspace definition fails in CI
    before it can reach the permission catalog or a production sync.
    """

    problems: list[str] = []
    seen_codes: set[str] = set()

    for definition in WORKSPACE_REGISTRY:
        if definition.code in seen_codes:
            problems.append(f"duplicate workspace code: {definition.code}")
        seen_codes.add(definition.code)

        # Workspace code becomes a permission-code segment; it must obey the
        # shared grammar (lowercase, letters/digits/hyphens, no underscores).
        if not definition.code or not definition.code.replace("-", "").isalnum():
            problems.append(f"invalid workspace code grammar: {definition.code}")
        elif not definition.code.islower():
            problems.append(f"workspace code must be lowercase: {definition.code}")
        if not definition.name:
            problems.append(f"workspace display name is required: {definition.code}")
        if definition.home_path is not None and (
            not definition.home_path
            or definition.home_path.startswith("/")
            or any(character.isspace() for character in definition.home_path)
        ):
            problems.append(
                f"workspace home_path must be a workspace-relative path: {definition.code}"
            )

    return problems
