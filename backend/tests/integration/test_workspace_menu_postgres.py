"""Workspace registry sync, association, and menu invariant tests.

All of these run against real PostgreSQL (recursive CTE, CHECK, FK, UUID,
TIMESTAMPTZ). No HTTP endpoints exist for these aggregates in Phase 3A, so
tests exercise the services the way the future CLI/API will.
"""

import pytest
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.departments.models import Department
from app.modules.rbac.catalog import Permissions
from app.modules.rbac.models import Permission, PermissionKind
from app.modules.rbac.service import PermissionCatalogService
from app.modules.workspaces.models import Menu, MenuType, Workspace, WorkspaceStatus
from app.modules.workspaces.registry import WORKSPACE_REGISTRY
from app.modules.workspaces.repository import WorkspaceRepository
from app.modules.workspaces.schemas import MenuCreate, MenuUpdate
from app.modules.workspaces.service import (
    MenuService,
    WorkspaceRegistryService,
    WorkspaceService,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.integration.conftest import committed_session

pytestmark = pytest.mark.postgres


async def _sync_permissions() -> None:
    async with committed_session() as session:
        await PermissionCatalogService(session).sync()
        await session.commit()


async def _sync_workspaces() -> None:
    async with committed_session() as session:
        await WorkspaceRegistryService(session).sync()
        await session.commit()


@pytest.fixture(autouse=True)
async def _seeded_database(db_session) -> None:
    """权限目录与 workspace registry 镜像在 schema 重置后先行就位。"""

    await _sync_permissions()
    await _sync_workspaces()


class TestRegistrySync:
    async def test_sync_mirrors_every_registered_workspace(self, db_session) -> None:
        rows = (
            (await db_session.execute(select(Workspace).order_by(Workspace.sort))).scalars().all()
        )

        assert [row.code for row in rows] == [d.code for d in WORKSPACE_REGISTRY]
        assert all(row.status is WorkspaceStatus.ACTIVE for row in rows)

    async def test_second_sync_is_idempotent(self, db_session) -> None:
        service = WorkspaceRegistryService(db_session)
        first = await service.sync()
        assert first.created == []
        assert len(first.unchanged) == len(WORKSPACE_REGISTRY)
        assert first.updated == []
        assert first.stale_disabled == []

        before = (await db_session.execute(select(Workspace))).scalars().all()
        signature_before = {(row.id, row.code, row.sort) for row in before}
        await service.sync()
        after = (await db_session.execute(select(Workspace))).scalars().all()
        assert {(row.id, row.code, row.sort) for row in after} == signature_before

    async def test_registry_removal_disables_row_stale(self, db_session) -> None:
        """registry 之外的同 code 行被标记 stale（disabled），绝不物理删除。"""

        session = db_session
        ghost = Workspace(code="ghost-workspace", name="Ghost", sort=999)
        session.add(ghost)
        await session.flush()

        report = await WorkspaceRegistryService(session).sync()

        assert "ghost-workspace" in report.stale_disabled
        await session.refresh(ghost)
        assert ghost.status is WorkspaceStatus.DISABLED
        assert ghost.deleted_at is None

    async def test_sync_keeps_identity_and_operator_status(self, db_session) -> None:
        """sync 更新 registry 拥有的展示字段，但不动 id/code/操作者设置的 status。"""

        session = db_session
        repo = WorkspaceRepository(session)
        workspace = await repo.get_by_code("operation")
        assert workspace is not None
        workspace.status = WorkspaceStatus.DISABLED  # 操作者手动禁用
        original_id = workspace.id
        original_sort = workspace.sort
        await session.flush()

        report = await WorkspaceRegistryService(session).sync()

        # registry 展示字段与库内一致：无 update；操作者设置的 status 保持原样。
        assert report.updated == []
        assert "operation" in report.unchanged
        await session.refresh(workspace)
        assert workspace.id == original_id  # 身份恒定
        assert workspace.code == "operation"  # code 恒定
        assert workspace.sort == original_sort  # registry sort 未变则不动
        assert workspace.status is WorkspaceStatus.DISABLED  # sync 不复活操作者禁用

    async def test_soft_deleted_row_blocks_its_code(self, db_session) -> None:
        session = db_session
        repo = WorkspaceRepository(session)
        workspace = await repo.get_by_code("operation")
        assert workspace is not None
        workspace.deleted_at = workspace.updated_at  # 模拟软删
        await session.flush()

        with pytest.raises(ValidationError, match="occupies code 'operation'"):
            await WorkspaceRegistryService(session).sync()

    async def test_workspace_code_uniqueness_enforced_by_database(self, db_session) -> None:
        session = db_session
        session.add(Workspace(code="finance", name="Duplicate", sort=999))
        with pytest.raises(IntegrityError):
            await session.flush()


class TestWorkspaceLifecycle:
    async def test_disable_enable_and_soft_delete(self, db_session) -> None:
        service = WorkspaceService(db_session)
        workspace = await service.get_active_by_code("tech")

        disabled = await service.disable(workspace.id)
        assert disabled.status is WorkspaceStatus.DISABLED
        with pytest.raises(NotFoundError):
            await service.get_active_by_code("tech")

        enabled = await service.enable(workspace.id)
        assert enabled.status is WorkspaceStatus.ACTIVE

        deleted = await service.soft_delete(workspace.id)
        assert deleted.deleted_at is not None
        with pytest.raises(NotFoundError):
            await service.get_active_by_id(workspace.id)

    async def test_list_active_excludes_disabled_and_deleted(self, db_session) -> None:
        service = WorkspaceService(db_session)
        hr = await service.get_active_by_code("hr")
        await service.disable(hr.id)
        await service.soft_delete(hr.id)

        codes = {workspace.code for workspace in await service.list_active()}
        assert "hr" not in codes
        assert {"operation", "product"} <= codes


class TestWorkspaceDepartmentAssociation:
    async def _department(self, code: str) -> Department:
        async with committed_session() as session:
            department = Department(name=code.title(), code=code, status="active")
            session.add(department)
            await session.commit()
            return department

    async def test_many_to_many_in_both_directions(self, db_session) -> None:
        service = WorkspaceService(db_session)
        operation = await service.get_active_by_code("operation")
        product = await service.get_active_by_code("product")
        engineering = await self._department("assoc-eng")
        operations_team = await self._department("assoc-ops")

        await service.associate_department(operation.id, engineering.id)
        await service.associate_department(operation.id, operations_team.id)
        await service.associate_department(product.id, engineering.id)

        departments_of_operation = await service.list_departments_for_workspace(operation.id)
        assert set(departments_of_operation) == {engineering.id, operations_team.id}

        workspaces_of_engineering = await service.list_workspaces_for_department(engineering.id)
        assert set(workspaces_of_engineering) == {operation.id, product.id}

    async def test_duplicate_association_rejected(self, db_session) -> None:
        service = WorkspaceService(db_session)
        workspace = await service.get_active_by_code("finance")
        department = await self._department("assoc-dup")

        await service.associate_department(workspace.id, department.id)
        with pytest.raises(ConflictError):
            await service.associate_department(workspace.id, department.id)

    async def test_unknown_reference_rejected(self, db_session) -> None:
        import uuid

        service = WorkspaceService(db_session)
        workspace = await service.get_active_by_code("hr")

        with pytest.raises(NotFoundError):
            await service.associate_department(workspace.id, uuid.uuid4())

    async def test_association_has_no_authorization_side_effect(self, db_session) -> None:
        """关联只是组织 metadata：role/permission/grant 计数零变化。"""

        from app.modules.rbac.models import Role, RolePermission, UserRole
        from sqlalchemy import func

        service = WorkspaceService(db_session)
        counts_before = {
            model: await db_session.scalar(select(func.count()).select_from(model))
            for model in (Role, Permission, UserRole, RolePermission)
        }

        workspace = await service.get_active_by_code("warehouse")
        department = await self._department("assoc-side-effect")
        await service.associate_department(workspace.id, department.id)

        counts_after = {
            model: await db_session.scalar(select(func.count()).select_from(model))
            for model in (Role, Permission, UserRole, RolePermission)
        }
        assert counts_before == counts_after


class TestMenuInvariants:
    async def _create_menu(self, db_session, **overrides) -> Menu:
        service = MenuService(db_session)
        from uuid import uuid4

        workspace = overrides.pop("workspace", None) or await WorkspaceRepository(
            db_session
        ).get_by_code("operation")
        assert workspace is not None
        payload = MenuCreate(
            workspace_id=workspace.id,
            code=overrides.pop("code", f"menu-{uuid4().hex[:8]}"),
            name=overrides.pop("name", "Dashboard"),
            menu_type=overrides.pop("menu_type", MenuType.PAGE),
            route_path=overrides.pop("route_path", "dashboard"),
            **overrides,
        )
        return await service.create(payload)

    async def test_create_root_child_and_tree(self, db_session) -> None:
        service = MenuService(db_session)
        root = await self._create_menu(
            db_session,
            code="directory-root",
            menu_type=MenuType.DIRECTORY,
            route_path=None,
            name="Operations",
        )
        child = await self._create_menu(
            db_session, code="child-page", parent_id=root.id, route_path="child"
        )

        tree = await service.tree(
            (await WorkspaceRepository(db_session).get_by_code("operation")).id
        )  # type: ignore[union-attr]
        assert len(tree) >= 1
        directory = next(node for node in tree if node.code == "directory-root")
        assert [node.code for node in directory.children] == [child.code]

    async def test_directory_rejects_route_and_component(self, db_session) -> None:
        service = MenuService(db_session)
        workspace = await WorkspaceRepository(db_session).get_by_code("operation")
        assert workspace is not None
        with pytest.raises(ValidationError, match="Directory menus"):
            await service.create(
                MenuCreate(
                    workspace_id=workspace.id,
                    code="bad-directory",
                    name="Bad",
                    menu_type=MenuType.DIRECTORY,
                    route_path="oops",
                )
            )

    async def test_page_requires_relative_route_path(self, db_session) -> None:
        service = MenuService(db_session)
        workspace = await WorkspaceRepository(db_session).get_by_code("operation")
        assert workspace is not None

        with pytest.raises(ValidationError, match="workspace-relative"):
            await service.create(
                MenuCreate(
                    workspace_id=workspace.id,
                    code="absolute-path",
                    name="Abs",
                    menu_type=MenuType.PAGE,
                    route_path="/operation/absolute",
                )
            )

    async def test_duplicate_code_within_workspace_rejected(self, db_session) -> None:
        service = MenuService(db_session)
        workspace = await WorkspaceRepository(db_session).get_by_code("operation")
        assert workspace is not None
        await service.create(
            MenuCreate(
                workspace_id=workspace.id,
                code="dup-code",
                name="First",
                menu_type=MenuType.PAGE,
                route_path="first",
            )
        )
        with pytest.raises(ConflictError):
            await service.create(
                MenuCreate(
                    workspace_id=workspace.id,
                    code="dup-code",
                    name="Second",
                    menu_type=MenuType.PAGE,
                    route_path="second",
                )
            )

    async def test_same_code_in_different_workspaces_allowed(self, db_session) -> None:
        service = MenuService(db_session)
        operation = await WorkspaceRepository(db_session).get_by_code("operation")
        product = await WorkspaceRepository(db_session).get_by_code("product")
        assert operation is not None
        assert product is not None

        for workspace in (operation, product):
            menu = await service.create(
                MenuCreate(
                    workspace_id=workspace.id,
                    code="overview",
                    name="Overview",
                    menu_type=MenuType.PAGE,
                    route_path="overview",
                )
            )
            assert menu.workspace_id == workspace.id

    async def test_cross_workspace_parent_rejected(self, db_session) -> None:
        service = MenuService(db_session)
        operation_menu = await self._create_menu(db_session, code="op-parent")
        product_workspace = await WorkspaceRepository(db_session).get_by_code("product")
        assert product_workspace is not None

        with pytest.raises(NotFoundError):
            await service.create(
                MenuCreate(
                    workspace_id=product_workspace.id,
                    code="cross-child",
                    name="Cross",
                    menu_type=MenuType.PAGE,
                    route_path="cross",
                    parent_id=operation_menu.id,
                )
            )

    async def test_self_parent_rejected(self, db_session) -> None:
        service = MenuService(db_session)
        menu = await self._create_menu(db_session, code="self-parent")

        with pytest.raises(ValidationError, match="own parent"):
            await service.move(menu.id, menu.id)

    async def test_move_to_descendant_rejected(self, db_session) -> None:
        service = MenuService(db_session)
        root = await self._create_menu(
            db_session, code="cte-root", menu_type=MenuType.DIRECTORY, route_path=None
        )
        child = await self._create_menu(
            db_session, code="cte-child", parent_id=root.id, route_path="child"
        )
        grandchild = await self._create_menu(
            db_session, code="cte-grandchild", parent_id=child.id, route_path="grandchild"
        )

        # 递归 CTE descendants 覆盖孙子层级。
        descendants = await service.descendant_ids(root.id)
        assert {child.id, grandchild.id} <= set(descendants)

        with pytest.raises(ValidationError, match="descendants"):
            await service.move(root.id, grandchild.id)

    async def test_move_to_unrelated_parent_succeeds(self, db_session) -> None:
        service = MenuService(db_session)
        root_a = await self._create_menu(
            db_session, code="move-root-a", menu_type=MenuType.DIRECTORY, route_path=None
        )
        child = await self._create_menu(
            db_session, code="move-child", parent_id=root_a.id, route_path="child"
        )
        root_b = await self._create_menu(
            db_session, code="move-root-b", menu_type=MenuType.DIRECTORY, route_path=None
        )

        moved = await service.move(child.id, root_b.id)
        assert moved.parent_id == root_b.id

    async def test_unknown_permission_code_rejected(self, db_session) -> None:
        service = MenuService(db_session)
        workspace = await WorkspaceRepository(db_session).get_by_code("operation")
        assert workspace is not None
        with pytest.raises(ValidationError, match="Unknown permission code"):
            await service.create(
                MenuCreate(
                    workspace_id=workspace.id,
                    code="bad-permission",
                    name="Bad",
                    menu_type=MenuType.PAGE,
                    route_path="bad",
                    permission_code="workspace:not-registered:access",
                )
            )

    async def test_known_workspace_access_code_accepted(self, db_session) -> None:
        menu = await self._create_menu(
            db_session,
            code="operation-entry",
            name="Operation Home",
            permission_code=Permissions.workspace_access("operation"),
        )
        assert menu.permission_code == "workspace:operation:access"

    async def test_disabled_permission_code_rejected(self, db_session) -> None:
        async with committed_session() as session:
            permission = await session.scalar(
                select(Permission).where(Permission.code == Permissions.USER_LIST)
            )
            assert permission is not None
            permission.status = permission.status.__class__.DISABLED
            await session.commit()

        with pytest.raises(ValidationError, match="Unknown permission code"):
            await self._create_menu(
                db_session,
                code="disabled-permission",
                name="Disabled",
                permission_code=Permissions.USER_LIST,
            )

    async def test_disable_soft_delete_and_code_retirement(self, db_session) -> None:
        service = MenuService(db_session)
        menu = await self._create_menu(db_session, code="retired-menu")

        disabled = await service.disable(menu.id)
        assert disabled.status.value == "disabled"

        deleted = await service.soft_delete(menu.id)
        assert deleted.deleted_at is not None
        with pytest.raises(NotFoundError):
            await service.get_active(menu.id)

        # 软删后 code 仍被占用（workspace 内全生命周期不可复用）。
        with pytest.raises(ConflictError):
            await self._create_menu(db_session, code="retired-menu")

    async def test_sort_stability(self, db_session) -> None:
        service = MenuService(db_session)
        workspace = await WorkspaceRepository(db_session).get_by_code("finance")
        assert workspace is not None
        from uuid import uuid4

        codes = [f"sorted-{uuid4().hex[:6]}" for _ in range(3)]
        for index, code in enumerate(codes):
            await service.create(
                MenuCreate(
                    workspace_id=workspace.id,
                    code=code,
                    name=code,
                    menu_type=MenuType.PAGE,
                    route_path=code,
                    sort=index,
                )
            )

        menus = await service.list_by_workspace(workspace.id)
        sorted_codes = [menu.code for menu in menus if menu.code.startswith("sorted-")]
        assert sorted_codes == codes

    async def test_update_permission_code_and_move(self, db_session) -> None:
        service = MenuService(db_session)
        menu = await self._create_menu(db_session, code="mutable-menu")

        updated = await service.update(
            menu.id,
            MenuUpdate(name="Renamed", permission_code=Permissions.workspace_access("tech")),
        )
        assert updated.name == "Renamed"
        assert updated.permission_code == "workspace:tech:access"

    async def test_catalog_has_one_access_permission_per_workspace(self, db_session) -> None:
        """sync-permissions 后每个 Registry workspace 恰好一个 access 行。"""

        rows = (
            (
                await db_session.execute(
                    select(Permission).where(Permission.kind == PermissionKind.WORKSPACE)
                )
            )
            .scalars()
            .all()
        )
        expected = {f"workspace:{d.code}:access" for d in WORKSPACE_REGISTRY}
        assert {row.code for row in rows} == expected
        assert all(row.status.value == "active" for row in rows)
