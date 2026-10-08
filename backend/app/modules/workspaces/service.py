"""Workspace registry sync, lifecycle, association, and menu invariants.

Services are the transaction boundary and stay free of HTTP. Rules that cross
aggregates (workspace ↔ department, menu ↔ permission catalog) are enforced
here so repositories keep executing queries only.
"""

from dataclasses import dataclass, field
from uuid import UUID

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.base import utc_now
from app.modules.departments.repository import DepartmentRepository
from app.modules.rbac.catalog import SYSTEM_PERMISSIONS
from app.modules.rbac.models import PermissionStatus
from app.modules.rbac.repository import PermissionRepository
from app.modules.workspaces.models import (
    Menu,
    MenuStatus,
    MenuType,
    Workspace,
    WorkspaceDepartment,
    WorkspaceStatus,
)
from app.modules.workspaces.registry import (
    WORKSPACE_REGISTRY,
    WorkspaceDefinition,
    validate_workspace_registry,
)
from app.modules.workspaces.repository import (
    MenuRepository,
    WorkspaceDepartmentRepository,
    WorkspaceRepository,
)
from app.modules.workspaces.schemas import (
    MenuCreate,
    MenuRead,
    MenuTreeNode,
    MenuUpdate,
)
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True)
class WorkspaceSyncReport:
    """Explicit sync outcome, mirroring the permission-sync reporting style."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    stale_disabled: list[str] = field(default_factory=list)


class WorkspaceRegistryService:
    """Mirror the code-owned workspace registry into the database.

    Sync is an explicit operator action (``python -m app.cli sync-workspaces``),
    never an application-startup side effect:

    - registry additions create their database row;
    - existing rows keep id/code; registry-owned display metadata is updated;
    - rows whose code left the registry are disabled (stale), never deleted,
    - status itself stays operator-owned: sync never re-enables a manually
      disabled workspace.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._workspaces = WorkspaceRepository(session)

    async def sync(self, *, dry_run: bool = False) -> WorkspaceSyncReport:
        problems = validate_workspace_registry()
        if problems:
            # Registry 是代码契约：畸形定义是编程错误，直接失败而非带病同步。
            raise ValidationError("; ".join(problems))

        report = WorkspaceSyncReport()
        registry_by_code = {definition.code: definition for definition in WORKSPACE_REGISTRY}
        existing_rows = await self._workspaces.list_mirrorable()
        existing_by_code = {workspace.code: workspace for workspace in existing_rows}

        # 软删行仍占用唯一 code：恢复是管理决策，sync 不得静默复活。
        for definition in WORKSPACE_REGISTRY:
            soft_deleted = await self._workspaces.get_any_by_code(definition.code)
            if (
                soft_deleted is not None
                and soft_deleted.deleted_at is not None
                and soft_deleted.code not in existing_by_code
            ):
                raise ValidationError(
                    f"Soft-deleted workspace row occupies code '{definition.code}'; "
                    "restore it explicitly before syncing."
                )

        for code, definition in registry_by_code.items():
            workspace = existing_by_code.get(code)
            if workspace is None:
                report.created.append(code)
                if not dry_run:
                    await self._workspaces.create(self._to_workspace(definition))
                continue

            changed = (
                workspace.name != definition.name
                or workspace.description != definition.description
                or workspace.icon != definition.icon
                or workspace.home_path != definition.home_path
                or workspace.sort != definition.sort
            )
            if changed:
                report.updated.append(code)
                if not dry_run:
                    workspace.name = definition.name
                    workspace.description = definition.description
                    workspace.icon = definition.icon
                    workspace.home_path = definition.home_path
                    workspace.sort = definition.sort
            if not changed:
                report.unchanged.append(code)

        for code, workspace in existing_by_code.items():
            if code not in registry_by_code and workspace.status == WorkspaceStatus.ACTIVE:
                report.stale_disabled.append(code)
                if not dry_run:
                    workspace.status = WorkspaceStatus.DISABLED

        # flush 令修改对同事务后续查询可见；commit 仍由调用方（CLI/请求事务）决定。
        if not dry_run:
            await self._session.flush()
        return report

    async def registry_codes_in_database(self) -> set[str]:
        rows = await self._workspaces.list_mirrorable()
        return {workspace.code for workspace in rows}

    @staticmethod
    def _to_workspace(definition: WorkspaceDefinition) -> Workspace:
        return Workspace(
            code=definition.code,
            name=definition.name,
            description=definition.description,
            icon=definition.icon,
            home_path=definition.home_path,
            sort=definition.sort,
            status=WorkspaceStatus.ACTIVE,
        )


class WorkspaceService:
    """Workspace lifecycle and association invariants.

    There is intentionally no workspace-create service path other than the
    registry sync: workspaces are code-owned. Association writes exist to keep
    the many-to-many metadata testable before any management API exists.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._workspaces = WorkspaceRepository(session)
        self._associations = WorkspaceDepartmentRepository(session)
        self._departments = DepartmentRepository(session)

    async def get_active_by_code(self, code: str) -> Workspace:
        workspace = await self._workspaces.get_by_code(code)
        if workspace is None or workspace.status is not WorkspaceStatus.ACTIVE:
            raise NotFoundError("Workspace not found.")
        return workspace

    async def get_active_by_id(self, workspace_id: UUID) -> Workspace:
        workspace = await self._workspaces.get_by_id(workspace_id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        return workspace

    async def list_active(self) -> list[Workspace]:
        return await self._workspaces.list_active()

    async def disable(self, workspace_id: UUID) -> Workspace:
        workspace = await self.get_active_by_id(workspace_id)
        workspace.status = WorkspaceStatus.DISABLED
        await self._session.flush()
        return workspace

    async def enable(self, workspace_id: UUID) -> Workspace:
        workspace = await self.get_active_by_id(workspace_id)
        workspace.status = WorkspaceStatus.ACTIVE
        await self._session.flush()
        return workspace

    async def soft_delete(self, workspace_id: UUID) -> Workspace:
        """软删保留历史身份；code 全生命周期不可复用（唯一约束继续占用）。"""

        workspace = await self.get_active_by_id(workspace_id)
        workspace.deleted_at = utc_now()
        await self._session.flush()
        return workspace

    async def associate_department(
        self, workspace_id: UUID, department_id: UUID
    ) -> WorkspaceDepartment:
        """建立产品/组织关联；这是 metadata，不是授权。"""

        await self.get_active_by_id(workspace_id)
        department = await self._departments.get_by_id(department_id)
        if department is None:
            raise NotFoundError("Department not found.")

        existing = await self._associations.get(workspace_id, department_id)
        if existing is not None:
            raise ConflictError("Department is already associated with this workspace.")
        return await self._associations.create(
            WorkspaceDepartment(workspace_id=workspace_id, department_id=department_id)
        )

    async def dissociate_department(self, workspace_id: UUID, department_id: UUID) -> bool:
        existing = await self._associations.get(workspace_id, department_id)
        if existing is None:
            return False
        await self._associations.delete(existing)
        return True

    async def list_departments_for_workspace(self, workspace_id: UUID) -> list[UUID]:
        await self.get_active_by_id(workspace_id)
        return await self._associations.list_departments_for_workspace(workspace_id)

    async def list_workspaces_for_department(self, department_id: UUID) -> list[UUID]:
        return await self._associations.list_workspaces_for_department(department_id)


class MenuService:
    """Menu invariants: workspace scoping, tree safety, catalog references.

    The menu tree is navigation metadata. ``permission_code`` is validated
    against the code-owned permission catalog (unknown codes are rejected) but
    never enforced here: backend authorization always answers through
    ``require_permission``/``AuthorizationService``, not menu visibility.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._menus = MenuRepository(session)
        self._workspaces = WorkspaceRepository(session)
        self._permissions = PermissionRepository(session)

    async def create(self, payload: MenuCreate) -> Menu:
        workspace = await self._require_active_workspace(payload.workspace_id)
        code = payload.code.strip()
        await self._ensure_code_available(workspace.id, code)
        await self._validate_parent(workspace.id, payload.parent_id)
        self._validate_navigation_metadata(
            menu_type=payload.menu_type.value,
            route_path=payload.route_path,
            component_key=payload.component_key,
        )
        if payload.permission_code is not None:
            await self._require_catalog_permission(payload.permission_code)

        menu = Menu(
            workspace_id=workspace.id,
            parent_id=payload.parent_id,
            code=code,
            name=payload.name.strip(),
            menu_type=MenuType(payload.menu_type.value),
            route_path=payload.route_path,
            component_key=payload.component_key,
            icon=payload.icon,
            permission_code=payload.permission_code,
            sort=payload.sort,
            visible=payload.visible,
            status=MenuStatus.ACTIVE,
        )
        return await self._menus.create(menu)

    async def get_active(self, menu_id: UUID) -> Menu:
        menu = await self._menus.get_by_id(menu_id)
        if menu is None:
            raise NotFoundError("Menu not found.")
        return menu

    async def update(self, menu_id: UUID, payload: MenuUpdate) -> Menu:
        menu = await self.get_active(menu_id)
        changes = payload.model_dump(exclude_unset=True)

        if "parent_id" in changes:
            await self._validate_move(menu, changes["parent_id"])
            menu.parent_id = changes["parent_id"]
        if "name" in changes and changes["name"] is not None:
            menu.name = changes["name"].strip()
        if "route_path" in changes:
            self._validate_navigation_metadata(
                menu_type=menu.menu_type.value,
                route_path=changes["route_path"],
                component_key=menu.component_key,
            )
            menu.route_path = changes["route_path"]
        if "component_key" in changes:
            menu.component_key = changes["component_key"]
        if "icon" in changes:
            menu.icon = changes["icon"]
        if "permission_code" in changes:
            if changes["permission_code"] is not None:
                await self._require_catalog_permission(changes["permission_code"])
            menu.permission_code = changes["permission_code"]
        if "sort" in changes and changes["sort"] is not None:
            menu.sort = changes["sort"]
        if "visible" in changes and changes["visible"] is not None:
            menu.visible = changes["visible"]

        await self._session.flush()
        return menu

    async def move(self, menu_id: UUID, parent_id: UUID | None) -> Menu:
        menu = await self.get_active(menu_id)
        await self._validate_move(menu, parent_id)
        menu.parent_id = parent_id
        await self._session.flush()
        return menu

    async def disable(self, menu_id: UUID) -> Menu:
        menu = await self.get_active(menu_id)
        menu.status = MenuStatus.DISABLED
        await self._session.flush()
        return menu

    async def enable(self, menu_id: UUID) -> Menu:
        menu = await self.get_active(menu_id)
        menu.status = MenuStatus.ACTIVE
        await self._session.flush()
        return menu

    async def soft_delete(self, menu_id: UUID) -> Menu:
        menu = await self.get_active(menu_id)
        menu.deleted_at = utc_now()
        await self._session.flush()
        return menu

    async def list_by_workspace(self, workspace_id: UUID) -> list[Menu]:
        await self._require_active_workspace(workspace_id)
        return await self._menus.list_by_workspace(workspace_id)

    async def tree(self, workspace_id: UUID) -> list[MenuTreeNode]:
        """服务端组装的导航树（composition 数据；不是授权边界）。"""

        menus = await self.list_by_workspace(workspace_id)
        reads = [MenuRead.model_validate(menu) for menu in menus]
        nodes = {read.id: MenuTreeNode(**read.model_dump(), children=[]) for read in reads}
        roots: list[MenuTreeNode] = []
        for menu in menus:
            node = nodes[menu.id]
            if menu.parent_id is not None and menu.parent_id in nodes:
                nodes[menu.parent_id].children.append(node)
            else:
                roots.append(node)
        return roots

    async def descendant_ids(self, menu_id: UUID) -> list[UUID]:
        await self.get_active(menu_id)
        return await self._menus.descendant_ids(menu_id)

    async def _require_active_workspace(self, workspace_id: UUID) -> Workspace:
        workspace = await self._workspaces.get_by_id(workspace_id)
        if workspace is None or workspace.status is not WorkspaceStatus.ACTIVE:
            raise NotFoundError("Workspace not found.")
        return workspace

    async def _ensure_code_available(self, workspace_id: UUID, code: str) -> None:
        # get_by_code 不过滤软删：workspace 内 code 全生命周期不可复用。
        if await self._menus.get_by_code(workspace_id, code) is not None:
            raise ConflictError("Menu code already exists in this workspace.")

    async def _validate_parent(self, workspace_id: UUID, parent_id: UUID | None) -> None:
        if parent_id is None:
            return
        parent = await self._menus.get_by_id(parent_id)
        if parent is None or parent.workspace_id != workspace_id:
            # 跨 workspace parent 破坏树的作用域不变式。
            raise NotFoundError("Parent menu not found.")

    async def _validate_move(self, menu: Menu, parent_id: UUID | None) -> None:
        if parent_id is None:
            return
        if parent_id == menu.id:
            raise ValidationError("A menu cannot be its own parent.")
        await self._validate_parent(menu.workspace_id, parent_id)
        descendant_ids = await self._menus.descendant_ids(menu.id)
        if parent_id in descendant_ids:
            raise ValidationError("A menu cannot be moved under one of its descendants.")

    async def _require_catalog_permission(self, permission_code: str) -> None:
        permission = await self._permissions.get_by_code(permission_code)
        if (
            permission is None
            or permission.status is not PermissionStatus.ACTIVE
            or permission.code not in {definition.code for definition in SYSTEM_PERMISSIONS}
        ):
            # 菜单只能引用 code-owned 目录中的权限码；任意字符串是配置错误。
            raise ValidationError(f"Unknown permission code: {permission_code}")

    @staticmethod
    def _validate_navigation_metadata(
        *, menu_type: str, route_path: str | None, component_key: str | None
    ) -> None:
        if menu_type == MenuType.DIRECTORY.value:
            if route_path is not None or component_key is not None:
                raise ValidationError("Directory menus carry no route or component metadata.")
            return
        # page：route_path 是导航 URL 元数据（workspace 内相对路径）。
        if (
            not route_path
            or route_path.startswith("/")
            or any(character.isspace() for character in route_path)
        ):
            raise ValidationError("Page menus need a workspace-relative route_path without spaces.")
