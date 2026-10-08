"""RBAC persistence, resolution, sync, and CLI contracts on real PostgreSQL."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password
from app.db.base import utc_now
from app.modules.auth.models import LocalCredential
from app.modules.rbac.catalog import (
    SUPER_ADMIN_ROLE_CODE,
    SYSTEM_ADMIN_ROLE_CODE,
    SYSTEM_PERMISSIONS,
)
from app.modules.rbac.models import (
    DataScopeType,
    Permission,
    PermissionKind,
    PermissionStatus,
    RoleStatus,
)
from app.modules.rbac.repository import (
    PermissionRepository,
    RolePermissionRepository,
    UserRoleRepository,
)
from app.modules.rbac.service import (
    AuthorizationService,
    PermissionCatalogService,
    RoleCreateRequest,
    RoleService,
)
from app.modules.users.models import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import (
    committed_session,
    create_isolated_engine,
)
from tests.integration.test_auth_service_postgres import seed_user

pytestmark = pytest.mark.postgres


def make_services(
    session: AsyncSession,
) -> tuple[RoleService, PermissionCatalogService, AuthorizationService]:
    return RoleService(session), PermissionCatalogService(session), AuthorizationService(session)


async def seed_system_data(session: AsyncSession) -> None:
    """Sync the catalog inside the transactional test session."""

    _, catalog_service, _ = make_services(session)
    await catalog_service.sync()


async def seed_credential(session: AsyncSession, user: User, password: str) -> None:
    session.add(
        LocalCredential(
            user_id=user.id,
            password_hash=hash_password(password),
            password_changed_at=utc_now(),
        )
    )
    await session.flush()


@pytest.fixture
async def clean_schema() -> None:
    """Reset the guarded schema for tests whose code owns its connection."""

    engine = await create_isolated_engine()
    await engine.dispose()
    return


class TestRoleService:
    async def test_create_role_with_unique_code(self, db_session: AsyncSession) -> None:
        roles, _, _ = make_services(db_session)

        role = await roles.create_role(
            RoleCreateRequest(
                code="operation_manager",
                name="运营经理",
                data_scope_type=DataScopeType.DEPARTMENT,
            )
        )

        assert role.id is not None
        assert role.status is RoleStatus.ACTIVE
        assert role.is_system is False
        assert role.data_scope_type is DataScopeType.DEPARTMENT

    async def test_duplicate_role_code_is_rejected(self, db_session: AsyncSession) -> None:
        roles, _, _ = make_services(db_session)
        await roles.create_role(RoleCreateRequest(code="ops_reader", name="Ops Reader"))

        with pytest.raises(ConflictError, match="ops_reader"):
            await roles.create_role(RoleCreateRequest(code="ops_reader", name="Duplicate"))

    async def test_soft_deleted_code_stays_unavailable(self, db_session: AsyncSession) -> None:
        roles, _, _ = make_services(db_session)
        role = await roles.create_role(RoleCreateRequest(code="retired_role", name="Retired"))

        await roles.soft_delete_role(role.id)

        with pytest.raises(ConflictError):
            await roles.create_role(RoleCreateRequest(code="retired_role", name="Recycled"))

    async def test_disable_role_keeps_row_but_exits_active_lists(
        self, db_session: AsyncSession
    ) -> None:
        roles, _, _ = make_services(db_session)
        role = await roles.create_role(RoleCreateRequest(code="freeze_me", name="Freeze"))

        await roles.disable_role(role.id)

        reloaded = await roles.get_by_code("freeze_me")
        assert reloaded is not None
        assert reloaded.status is RoleStatus.DISABLED
        assert reloaded.deleted_at is None
        assert all(active.code != "freeze_me" for active in await roles.list_active())

    async def test_soft_delete_marks_deleted_at(self, db_session: AsyncSession) -> None:
        roles, _, _ = make_services(db_session)
        role = await roles.create_role(RoleCreateRequest(code="gone_soon", name="Gone"))

        deleted = await roles.soft_delete_role(role.id)

        assert deleted.deleted_at is not None
        assert deleted.status is RoleStatus.DISABLED
        assert await roles.get_by_code("gone_soon") is None
        assert await roles.get_by_code("gone_soon", include_deleted=True) is not None

    async def test_system_roles_are_protected(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        roles, _, _ = make_services(db_session)
        super_admin = await roles.get_by_code(SUPER_ADMIN_ROLE_CODE)
        assert super_admin is not None

        with pytest.raises(ConflictError, match="System roles cannot be disabled"):
            await roles.disable_role(super_admin.id)
        with pytest.raises(ConflictError, match="System roles cannot be deleted"):
            await roles.soft_delete_role(super_admin.id)


class TestPermissionCatalogSync:
    async def test_first_sync_seeds_permissions_roles_and_grants(
        self, db_session: AsyncSession
    ) -> None:
        _, catalog, _ = make_services(db_session)

        report = await catalog.sync()

        assert sorted(report.created) == sorted(d.code for d in SYSTEM_PERMISSIONS)
        assert sorted(report.roles_created) == ["security_auditor", "super_admin", "system_admin"]
        assert report.stale_disabled == []
        assert report.role_permissions_added
        assert not any(
            grant.startswith(f"{SUPER_ADMIN_ROLE_CODE}:") for grant in report.role_permissions_added
        )

        roles, _, _ = make_services(db_session)
        super_admin = await roles.get_by_code(SUPER_ADMIN_ROLE_CODE)
        assert super_admin is not None
        assert super_admin.is_system is True

    async def test_second_sync_is_a_no_op(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        _, catalog, _ = make_services(db_session)

        report = await catalog.sync()

        assert report.created == []
        assert report.updated == []
        assert report.reenabled == []
        assert report.stale_disabled == []
        assert report.roles_created == []
        assert report.role_permissions_added == []
        assert len(report.unchanged) == len(SYSTEM_PERMISSIONS)

    async def test_sync_keeps_permission_ids_and_codes_stable(
        self, db_session: AsyncSession
    ) -> None:
        await seed_system_data(db_session)
        _, catalog, _ = make_services(db_session)

        before = {p.code: p.id for p in await catalog._permissions.list_all()}
        await catalog.sync()
        after = {p.code: p.id for p in await catalog._permissions.list_all()}

        assert before == after

    async def test_stale_permission_is_disabled_not_deleted(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        _, catalog, _ = make_services(db_session)
        db_session.add(
            Permission(
                code="legacy:ghost:action",
                name="Removed legacy capability",
                kind=PermissionKind.ACTION,
                module="ghost",
                status=PermissionStatus.ACTIVE,
            )
        )
        await db_session.flush()

        report = await catalog.sync()

        assert "legacy:ghost:action" in report.stale_disabled
        reloaded = await catalog._permissions.get_by_code("legacy:ghost:action")
        assert reloaded is not None
        assert reloaded.status is PermissionStatus.DISABLED  # row kept for history

    async def test_removed_catalog_code_gets_reenabled_on_return(
        self, db_session: AsyncSession
    ) -> None:
        await seed_system_data(db_session)
        _, catalog, _ = make_services(db_session)
        code = SYSTEM_PERMISSIONS[0].code
        permission = await catalog._permissions.get_by_code(code)
        assert permission is not None
        permission.status = PermissionStatus.DISABLED
        await db_session.flush()

        report = await catalog.sync()

        assert code in report.reenabled
        reloaded = await catalog._permissions.get_by_code(code)
        assert reloaded is not None
        assert reloaded.status is PermissionStatus.ACTIVE

    async def test_dry_run_writes_nothing(self, db_session: AsyncSession) -> None:
        _, catalog, _ = make_services(db_session)

        report = await catalog.sync(dry_run=True)

        assert report.created  # plan reports the work…
        rows = (await db_session.scalars(select(Permission))).all()
        assert rows == []  # …but nothing was written


class TestUserRoleGrants:
    async def test_assign_multiple_roles_and_resolve(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        user = await seed_user(db_session, username="multi-role")
        _, _, authorization = make_services(db_session)

        await authorization.assign_role(user.id, SUPER_ADMIN_ROLE_CODE)
        await authorization.assign_role(user.id, SYSTEM_ADMIN_ROLE_CODE)

        assert await authorization.get_role_codes(user.id) == [
            SUPER_ADMIN_ROLE_CODE,
            SYSTEM_ADMIN_ROLE_CODE,
        ]

    async def test_duplicate_assignment_is_idempotent(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        user = await seed_user(db_session, username="dup-assign")
        _, _, authorization = make_services(db_session)

        _, first = await authorization.assign_role(user.id, SYSTEM_ADMIN_ROLE_CODE)
        _, second = await authorization.assign_role(user.id, SYSTEM_ADMIN_ROLE_CODE)

        assert first is True
        assert second is False
        assert len(await authorization.get_role_codes(user.id)) == 1

    async def test_assign_unknown_or_inactive_role_fails(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        user = await seed_user(db_session, username="assign-fail")
        _, _, authorization = make_services(db_session)

        with pytest.raises(NotFoundError):
            await authorization.assign_role(user.id, "no_such_role")

        roles, _, _ = make_services(db_session)
        custom = await roles.create_role(RoleCreateRequest(code="sleeping", name="Sleeping"))
        await roles.disable_role(custom.id)
        with pytest.raises(ConflictError):
            await authorization.assign_role(user.id, "sleeping")

    async def test_remove_role(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        user = await seed_user(db_session, username="remove-me")
        _, _, authorization = make_services(db_session)
        await authorization.assign_role(user.id, SYSTEM_ADMIN_ROLE_CODE)

        assert await authorization.remove_role(user.id, SYSTEM_ADMIN_ROLE_CODE) is True
        assert await authorization.remove_role(user.id, SYSTEM_ADMIN_ROLE_CODE) is False
        assert await authorization.get_role_codes(user.id) == []
        assert await authorization.get_effective_permission_codes(user.id) == set()


class TestEffectivePermissions:
    async def test_single_role_resolves_its_permissions(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        user = await seed_user(db_session, username="solo")
        _, _, authorization = make_services(db_session)

        await authorization.assign_role(user.id, "security_auditor")

        codes = await authorization.get_effective_permission_codes(user.id)
        assert "system:user:list" in codes
        assert "system:user:create" not in codes
        assert "system:role:assign" not in codes

    async def test_multiple_roles_union_and_deduplicate(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        user = await seed_user(db_session, username="union-user")
        _, _, authorization = make_services(db_session)

        await authorization.assign_role(user.id, "security_auditor")
        await authorization.assign_role(user.id, SYSTEM_ADMIN_ROLE_CODE)

        codes = await authorization.get_effective_permission_codes(user.id)
        # system_admin 持有全部 action 权限；workspace access 属业务授权，
        # 不随平台角色自动获得（Phase 3A 边界）。
        assert codes == {
            definition.code
            for definition in SYSTEM_PERMISSIONS
            if definition.kind is PermissionKind.ACTION
        }

    async def test_disabled_role_contributes_nothing(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        user = await seed_user(db_session, username="frozen")
        roles, _, authorization = make_services(db_session)
        await authorization.assign_role(user.id, SYSTEM_ADMIN_ROLE_CODE)
        custom = await roles.create_role(RoleCreateRequest(code="helper", name="Helper"))
        assert custom.id is not None
        await authorization.assign_role(user.id, "helper")
        await roles.disable_role(custom.id)

        codes = await authorization.get_effective_permission_codes(user.id)
        # system_admin still contributes; helper (disabled) adds nothing extra.
        assert codes == {
            definition.code
            for definition in SYSTEM_PERMISSIONS
            if definition.kind is PermissionKind.ACTION
        }

        await authorization.remove_role(user.id, SYSTEM_ADMIN_ROLE_CODE)
        assert await authorization.get_effective_permission_codes(user.id) == set()

    async def test_soft_deleted_role_contributes_nothing(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        user = await seed_user(db_session, username="deleted-role-user")
        roles, _, authorization = make_services(db_session)
        custom = await roles.create_role(RoleCreateRequest(code="doomed", name="Doomed"))
        assert custom.id is not None
        await authorization.assign_role(user.id, "doomed")

        permissions = PermissionRepository(db_session)
        view_permission = await permissions.get_by_code("system:user:view")
        assert view_permission is not None
        await RolePermissionRepository(db_session).assign(custom.id, view_permission.id)
        assert await authorization.get_effective_permission_codes(user.id) == {"system:user:view"}

        await roles.soft_delete_role(custom.id)
        assert await authorization.get_effective_permission_codes(user.id) == set()

    async def test_disabled_permission_contributes_nothing(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        user = await seed_user(db_session, username="perm-off")
        _, catalog, authorization = make_services(db_session)
        await authorization.assign_role(user.id, SYSTEM_ADMIN_ROLE_CODE)

        permission = await catalog._permissions.get_by_code("system:user:create")
        assert permission is not None
        permission.status = PermissionStatus.DISABLED
        await db_session.flush()

        codes = await authorization.get_effective_permission_codes(user.id)
        assert "system:user:create" not in codes
        assert "system:user:list" in codes

    async def test_user_with_no_roles_has_no_permissions(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        user = await seed_user(db_session, username="plain")
        _, _, authorization = make_services(db_session)

        assert await authorization.get_role_codes(user.id) == []
        assert await authorization.get_effective_permission_codes(user.id) == set()
        assert await authorization.has_permission(user.id, "system:user:list") is False

    async def test_user_id_outside_table_resolves_to_nothing(
        self, db_session: AsyncSession
    ) -> None:
        await seed_system_data(db_session)
        _, _, authorization = make_services(db_session)

        assert await authorization.get_effective_permission_codes(uuid4()) == set()


class TestSuperAdmin:
    async def test_super_admin_resolves_all_active_permissions(
        self, db_session: AsyncSession
    ) -> None:
        await seed_system_data(db_session)
        user = await seed_user(db_session, username="root-holder")
        _, _, authorization = make_services(db_session)

        await authorization.assign_role(user.id, SUPER_ADMIN_ROLE_CODE)

        codes = await authorization.get_effective_permission_codes(user.id)
        assert codes == {definition.code for definition in SYSTEM_PERMISSIONS}

    async def test_super_admin_covers_permissions_added_after_assignment(
        self, db_session: AsyncSession
    ) -> None:
        await seed_system_data(db_session)
        user = await seed_user(db_session, username="future-proof")
        _, _, authorization = make_services(db_session)
        await authorization.assign_role(user.id, SUPER_ADMIN_ROLE_CODE)

        db_session.add(
            Permission(
                code="system:future-widget:list",
                name="Future widget list",
                kind=PermissionKind.ACTION,
                module="future-widget",
                status=PermissionStatus.ACTIVE,
            )
        )
        await db_session.flush()

        codes = await authorization.get_effective_permission_codes(user.id)
        assert "system:future-widget:list" in codes

    async def test_no_username_bypass_without_role_assignment(
        self, db_session: AsyncSession
    ) -> None:
        """A user literally named "admin" has zero permissions without grants."""

        await seed_system_data(db_session)
        _, _, authorization = make_services(db_session)

        admin_named_user: User = await seed_user(db_session, username="admin")

        assert await authorization.get_effective_permission_codes(admin_named_user.id) == set()
        assert await authorization.has_permission(admin_named_user.id, "system:user:list") is False

    async def test_disabled_super_admin_role_stops_expansion(
        self, db_session: AsyncSession
    ) -> None:
        """Resolution has no special case: a non-active super_admin role is inert.

        ``RoleService`` refuses to disable system roles; this test flips the
        row directly to prove the resolver predicate itself, not the service
        guard, is what stops expansion.
        """

        await seed_system_data(db_session)
        user = await seed_user(db_session, username="root-frozen")
        _, _, authorization = make_services(db_session)
        await authorization.assign_role(user.id, SUPER_ADMIN_ROLE_CODE)

        roles, _, _ = make_services(db_session)
        super_admin = await roles.get_by_code(SUPER_ADMIN_ROLE_CODE)
        assert super_admin is not None
        super_admin.status = RoleStatus.DISABLED  # direct data change; no service path

        assert await authorization.get_effective_permission_codes(user.id) == set()


class TestRolePermissionGrants:
    async def test_assign_is_idempotent_and_remove_works(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        roles, _, _ = make_services(db_session)
        custom = await roles.create_role(RoleCreateRequest(code="custom_mgr", name="Custom"))
        assert custom.id is not None

        permissions = PermissionRepository(db_session)
        grants = RolePermissionRepository(db_session)
        list_permission = await permissions.get_by_code("system:user:list")
        assert list_permission is not None

        await grants.assign(custom.id, list_permission.id)
        await grants.assign(custom.id, list_permission.id)  # duplicate: idempotent

        assert len(await grants.list_permission_ids_for_role(custom.id)) == 1

        assert await grants.remove(custom.id, list_permission.id) is True
        assert await grants.remove(custom.id, list_permission.id) is False
        assert await grants.list_permission_ids_for_role(custom.id) == set()


class TestAssignmentEvidence:
    async def test_assigned_by_is_recorded(self, db_session: AsyncSession) -> None:
        await seed_system_data(db_session)
        actor = await seed_user(db_session, username="actor-admin")
        subject = await seed_user(db_session, username="subject-user")
        _, _, authorization = make_services(db_session)

        role_id, _ = await authorization.assign_role(
            subject.id, SYSTEM_ADMIN_ROLE_CODE, assigned_by=actor.id
        )

        grant = await UserRoleRepository(db_session).get(subject.id, role_id)
        assert grant is not None
        assert grant.assigned_by == actor.id
        assert grant.assigned_at is not None


class TestAuthMeProfile:
    async def test_me_returns_roles_and_permissions(self, api_client) -> None:
        password = "Me-Profile-Passphrase!"
        async with committed_session() as session:
            user = await seed_user(session, username="me-rbac", with_credential=False)
            await seed_credential(session, user, password)
            await PermissionCatalogService(session).sync()
            await AuthorizationService(session).assign_role(user.id, SYSTEM_ADMIN_ROLE_CODE)
            await session.commit()

        login = await api_client.post(
            "/api/v1/auth/login", json={"username": "me-rbac", "password": password}
        )
        assert login.status_code == 200
        token = login.json()["data"]["access_token"]

        response = await api_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["roles"] == [SYSTEM_ADMIN_ROLE_CODE]
        assert data["permissions"] == sorted(
            d.code for d in SYSTEM_PERMISSIONS if d.kind is PermissionKind.ACTION
        )
        assert "workspaces" not in data
        assert "menus" not in data
        assert "data_scope" not in data

    async def test_me_without_roles_returns_empty_collections(self, api_client) -> None:
        password = "No-Roles-Passphrase!"
        async with committed_session() as session:
            user = await seed_user(session, username="me-plain", with_credential=False)
            await seed_credential(session, user, password)
            await PermissionCatalogService(session).sync()
            await session.commit()

        login = await api_client.post(
            "/api/v1/auth/login", json={"username": "me-plain", "password": password}
        )
        token = login.json()["data"]["access_token"]

        response = await api_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["roles"] == []
        assert data["permissions"] == []


class TestCliCommands:
    """CLI commands own their sessions; run against a freshly reset schema."""

    @pytest.fixture(autouse=True)
    async def fresh_process_engine(self) -> AsyncIterator[None]:
        """Rebuild the process-wide engine per test: pools are loop-bound."""

        from app.db.session import dispose_engine

        await dispose_engine()
        try:
            yield
        finally:
            await dispose_engine()

    async def test_sync_permissions_command_is_idempotent(self, clean_schema: None) -> None:
        from app.cli import sync_permissions

        assert await sync_permissions(dry_run=False) == 0
        assert await sync_permissions(dry_run=False) == 0

        async with committed_session() as session:
            rows = (await session.scalars(select(Permission))).all()
            assert {permission.code for permission in rows} == {
                definition.code for definition in SYSTEM_PERMISSIONS
            }

    async def test_sync_permissions_dry_run_writes_nothing(self, clean_schema: None) -> None:
        from app.cli import sync_permissions

        assert await sync_permissions(dry_run=True) == 0
        async with committed_session() as session:
            rows = (await session.scalars(select(Permission))).all()
            assert rows == []

    async def test_assign_role_command(self, clean_schema: None) -> None:
        from app.cli import assign_role, sync_permissions

        assert await sync_permissions(dry_run=False) == 0
        async with committed_session() as session:
            await seed_user(session, username="cli-admin", with_credential=False)
            await session.commit()

        assert (
            await assign_role(
                username="cli-admin",
                role_code=SUPER_ADMIN_ROLE_CODE,
                assigned_by_username=None,
            )
            == 0
        )
        # Second run is idempotent; unknown users/roles fail with exit code 1.
        assert (
            await assign_role(
                username="cli-admin",
                role_code=SUPER_ADMIN_ROLE_CODE,
                assigned_by_username=None,
            )
            == 0
        )
        assert (
            await assign_role(
                username="ghost-user",
                role_code=SUPER_ADMIN_ROLE_CODE,
                assigned_by_username=None,
            )
            == 1
        )
        assert (
            await assign_role(
                username="cli-admin",
                role_code="no_such_role",
                assigned_by_username=None,
            )
            == 1
        )

    async def test_show_user_roles_command(self, clean_schema: None) -> None:
        from app.cli import _print_user_roles, assign_role, sync_permissions

        assert await sync_permissions(dry_run=False) == 0
        async with committed_session() as session:
            await seed_user(session, username="cli-viewer", with_credential=False)
            await session.commit()
        assert (
            await assign_role(
                username="cli-viewer",
                role_code=SYSTEM_ADMIN_ROLE_CODE,
                assigned_by_username=None,
            )
            == 0
        )

        assert await _print_user_roles("cli-viewer") == 0
        assert await _print_user_roles("ghost-viewer") == 1
