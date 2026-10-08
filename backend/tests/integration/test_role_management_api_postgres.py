"""Role / Permission Management API 与两类授权操作的集成测试。"""

from uuid import uuid4

import pytest
from app.modules.rbac.catalog import (
    SECURITY_AUDITOR_ROLE_CODE,
    SUPER_ADMIN_ROLE_CODE,
    Permissions,
)
from httpx import AsyncClient
from sqlalchemy import select

from tests.integration.conftest import (
    committed_session,
    request_as,
)

pytestmark = pytest.mark.postgres

ANY_ROLE_ID = str(uuid4())
ANY_USER_ID = str(uuid4())

ROLE_ENDPOINTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/api/v1/roles", None),
    ("GET", f"/api/v1/roles/{ANY_ROLE_ID}", None),
    ("POST", "/api/v1/roles", {"code": "ops-manager", "name": "Ops Manager"}),
    ("PATCH", f"/api/v1/roles/{ANY_ROLE_ID}", {"name": "Renamed"}),
    ("POST", f"/api/v1/roles/{ANY_ROLE_ID}/disable", None),
    ("POST", f"/api/v1/roles/{ANY_ROLE_ID}/enable", None),
    ("GET", f"/api/v1/roles/{ANY_ROLE_ID}/permissions", None),
    ("PUT", f"/api/v1/roles/{ANY_ROLE_ID}/permissions", {"permission_codes": ["system:user:list"]}),
]

PERMISSION_ENDPOINTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/api/v1/permissions", None),
    ("GET", f"/api/v1/permissions/{ANY_ROLE_ID}", None),
]

ASSIGNMENT_ENDPOINTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", f"/api/v1/users/{ANY_USER_ID}/roles", None),
    ("POST", f"/api/v1/users/{ANY_USER_ID}/roles/{ANY_ROLE_ID}", None),
    ("DELETE", f"/api/v1/users/{ANY_USER_ID}/roles/{ANY_ROLE_ID}", None),
]


@pytest.mark.parametrize(
    ("method", "path", "body"), ROLE_ENDPOINTS + PERMISSION_ENDPOINTS + ASSIGNMENT_ENDPOINTS
)
async def test_unauthenticated_is_401(
    api_client: AsyncClient, method: str, path: str, body: dict[str, object] | None
) -> None:
    assert (await request_as(api_client, None, method, path, body)).status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"), ROLE_ENDPOINTS + PERMISSION_ENDPOINTS + ASSIGNMENT_ENDPOINTS
)
async def test_without_permission_is_403(
    api_client: AsyncClient,
    management_accounts: dict[str, str],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    response = await request_as(api_client, management_accounts["plain_token"], method, path, body)
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "body"), ROLE_ENDPOINTS + PERMISSION_ENDPOINTS + ASSIGNMENT_ENDPOINTS
)
async def test_super_admin_allowed(
    api_client: AsyncClient,
    management_accounts: dict[str, str],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    response = await request_as(api_client, management_accounts["super_token"], method, path, body)
    assert response.status_code not in (401, 403)


async def _create_role(api_client: AsyncClient, token: str, code: str) -> str:
    response = await request_as(
        api_client, token, "POST", "/api/v1/roles", {"code": code, "name": code.title()}
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


class TestRoleRules:
    async def test_create_detail_and_lifecycle(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        role_id = await _create_role(api_client, token, "lifecycle-role")

        renamed = await request_as(
            api_client, token, "PATCH", f"/api/v1/roles/{role_id}", {"name": "Lifecycle"}
        )
        assert renamed.json()["data"]["name"] == "Lifecycle"

        disabled = await request_as(api_client, token, "POST", f"/api/v1/roles/{role_id}/disable")
        assert disabled.json()["data"]["status"] == "disabled"

        listing = await request_as(api_client, token, "GET", "/api/v1/roles")
        codes = {role["code"]: role["status"] for role in listing.json()["data"]}
        assert codes["lifecycle-role"] == "disabled"  # disabled 可见（管理需要）

        enabled = await request_as(api_client, token, "POST", f"/api/v1/roles/{role_id}/enable")
        assert enabled.json()["data"]["status"] == "active"

    async def test_duplicate_code_conflicts_even_with_soft_deleted(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        role_id = await _create_role(api_client, token, "retired-code")
        async with committed_session() as session:
            from uuid import UUID

            from app.modules.rbac.service import RoleService

            await RoleService(session).soft_delete_role(UUID(role_id))
            await session.commit()

        duplicate = await request_as(
            api_client, token, "POST", "/api/v1/roles", {"code": "retired-code", "name": "X"}
        )
        assert duplicate.status_code == 409

    async def test_system_role_protection(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        async with committed_session() as session:
            from app.modules.rbac.service import RoleService

            role = await RoleService(session).get_by_code(SUPER_ADMIN_ROLE_CODE)
            assert role is not None
            role_id = str(role.id)

        # 禁用/删除走 service 守卫 -> 409；PATCH 无法触及 code/is_system（schema 不含）。
        disable = await request_as(api_client, token, "POST", f"/api/v1/roles/{role_id}/disable")
        assert disable.status_code == 409

        patched = await request_as(
            api_client,
            token,
            "PATCH",
            f"/api/v1/roles/{role_id}",
            {"name": "Hacked", "code": "not-admin", "is_system": False},
        )
        assert patched.status_code == 200
        data = patched.json()["data"]
        assert data["code"] == SUPER_ADMIN_ROLE_CODE  # code 恒不可改
        assert data["is_system"] is True  # is_system 恒不可改


class TestPermissionReadApi:
    async def test_list_with_filters_and_pagination(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]

        all_permissions = await request_as(
            api_client, token, "GET", "/api/v1/permissions?page_size=100"
        )
        assert all_permissions.status_code == 200
        body = all_permissions.json()
        assert body["meta"]["total"] >= 23

        module_filter = await request_as(
            api_client, token, "GET", "/api/v1/permissions?module=user"
        )
        assert module_filter.json()["meta"]["total"] == 5

        keyword = await request_as(
            api_client, token, "GET", "/api/v1/permissions?keyword=system:role:"
        )
        assert keyword.json()["meta"]["total"] == 6

    async def test_permissions_are_read_only(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        """POST/PATCH/DELETE /permissions 必须不存在（405 = 路由未注册该方法）。"""

        token = management_accounts["super_token"]
        post = await request_as(api_client, token, "POST", "/api/v1/permissions", {"code": "x:x:x"})
        delete = await request_as(api_client, token, "DELETE", "/api/v1/permissions")
        assert post.status_code == 405
        assert delete.status_code == 405


class TestRolePermissionReplacement:
    async def test_replace_semantics_reports_add_remove_unchanged(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        role_id = await _create_role(api_client, token, "perm-target")

        first = await request_as(
            api_client,
            token,
            "PUT",
            f"/api/v1/roles/{role_id}/permissions",
            {"permission_codes": [Permissions.USER_LIST, Permissions.USER_VIEW]},
        )
        assert first.status_code == 200
        report = first.json()["data"]
        assert sorted(report["added"]) == [Permissions.USER_LIST, Permissions.USER_VIEW]
        assert report["removed"] == []

        second = await request_as(
            api_client,
            token,
            "PUT",
            f"/api/v1/roles/{role_id}/permissions",
            {"permission_codes": [Permissions.USER_LIST, Permissions.DEPARTMENT_LIST]},
        )
        report = second.json()["data"]
        assert report["added"] == [Permissions.DEPARTMENT_LIST]
        assert report["removed"] == [Permissions.USER_VIEW]
        assert report["unchanged"] == [Permissions.USER_LIST]

        # 幂等：同一集合再次提交 -> 空变更。
        third = await request_as(
            api_client,
            token,
            "PUT",
            f"/api/v1/roles/{role_id}/permissions",
            {"permission_codes": [Permissions.USER_LIST, Permissions.DEPARTMENT_LIST]},
        )
        report = third.json()["data"]
        assert report["added"] == []
        assert report["removed"] == []

        readback = await request_as(
            api_client, token, "GET", f"/api/v1/roles/{role_id}/permissions"
        )
        assert set(readback.json()["data"]["permission_codes"]) == {
            Permissions.USER_LIST,
            Permissions.DEPARTMENT_LIST,
        }

    async def test_unknown_or_disabled_code_is_422(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        role_id = await _create_role(api_client, token, "strict-role")

        unknown = await request_as(
            api_client,
            token,
            "PUT",
            f"/api/v1/roles/{role_id}/permissions",
            {"permission_codes": ["system:not-real:permission"]},
        )
        assert unknown.status_code == 422

        # 先禁用一个目录权限，再尝试授予 -> 422。
        async with committed_session() as session:
            from app.modules.rbac.models import Permission, PermissionStatus

            permission = await session.scalar(
                select(Permission).where(Permission.code == Permissions.USER_CREATE)
            )
            assert permission is not None
            permission.status = PermissionStatus.DISABLED
            await session.commit()

        disabled = await request_as(
            api_client,
            token,
            "PUT",
            f"/api/v1/roles/{role_id}/permissions",
            {"permission_codes": [Permissions.USER_CREATE]},
        )
        assert disabled.status_code == 422

    async def test_super_admin_permissions_are_not_editable(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        async with committed_session() as session:
            from app.modules.rbac.service import RoleService

            role = await RoleService(session).get_by_code(SUPER_ADMIN_ROLE_CODE)
            assert role is not None
            role_id = str(role.id)

        response = await request_as(
            api_client,
            token,
            "PUT",
            f"/api/v1/roles/{role_id}/permissions",
            {"permission_codes": [Permissions.USER_LIST]},
        )
        assert response.status_code == 409

        readback = await request_as(
            api_client, token, "GET", f"/api/v1/roles/{role_id}/permissions"
        )
        assert readback.json()["data"]["permission_codes"] == []  # 恒为空集：动态展开


class TestUserRoleAssignment:
    async def test_assign_is_idempotent_and_records_operator(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        target_id = management_accounts["plain_id"]
        async with committed_session() as session:
            from app.modules.rbac.service import RoleService

            role = await RoleService(session).get_by_code(SECURITY_AUDITOR_ROLE_CODE)
            assert role is not None
            role_id = str(role.id)

        first = await request_as(
            api_client, token, "POST", f"/api/v1/users/{target_id}/roles/{role_id}"
        )
        assert first.status_code == 200
        assert first.json()["data"]["newly_assigned"] is True

        duplicate = await request_as(
            api_client, token, "POST", f"/api/v1/users/{target_id}/roles/{role_id}"
        )
        assert duplicate.json()["data"]["newly_assigned"] is False

        grants = await request_as(api_client, token, "GET", f"/api/v1/users/{target_id}/roles")
        grant = grants.json()["data"][0]
        assert grant["role_code"] == SECURITY_AUDITOR_ROLE_CODE
        assert grant["assigned_by"] == management_accounts["super_id"]  # 操作者证据

        removal = await request_as(
            api_client, token, "DELETE", f"/api/v1/users/{target_id}/roles/{role_id}"
        )
        assert removal.json()["data"]["removed"] is True
        again = await request_as(
            api_client, token, "DELETE", f"/api/v1/users/{target_id}/roles/{role_id}"
        )
        assert again.json()["data"]["removed"] is False

    async def test_unknown_user_or_role_is_404(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        assert (
            await request_as(api_client, token, "POST", f"/api/v1/users/{uuid4()}/roles/{uuid4()}")
        ).status_code == 404

    async def test_disabled_role_cannot_be_assigned(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        role_id = await _create_role(api_client, token, "sleepy-role")
        await request_as(api_client, token, "POST", f"/api/v1/roles/{role_id}/disable")

        response = await request_as(
            api_client,
            token,
            "POST",
            f"/api/v1/users/{management_accounts['plain_id']}/roles/{role_id}",
        )
        assert response.status_code == 409

    async def test_permission_change_applies_on_next_request(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        """无缓存契约：/auth/me 的 permissions 在授权变更后下一请求立即变化。"""

        token = management_accounts["super_token"]
        target_id = management_accounts["plain_id"]
        # matrix-plain 的凭据由 management_accounts fixture 创建，直接登录。
        password = "Matrix-Passphrase-1!"

        async with committed_session() as session:
            from app.modules.rbac.service import RoleService

            auditor = await RoleService(session).get_by_code(SECURITY_AUDITOR_ROLE_CODE)
            assert auditor is not None
            role_id = str(auditor.id)

        login = await api_client.post(
            "/api/v1/auth/login", json={"username": "matrix-plain", "password": password}
        )
        victim_token = login.json()["data"]["access_token"]

        async def me_permissions() -> list[str]:
            me = await request_as(api_client, victim_token, "GET", "/api/v1/auth/me")
            return me.json()["data"]["permissions"]

        assert await me_permissions() == []

        await request_as(api_client, token, "POST", f"/api/v1/users/{target_id}/roles/{role_id}")
        after_assign = await me_permissions()
        assert Permissions.USER_LIST in after_assign

        await request_as(api_client, token, "DELETE", f"/api/v1/users/{target_id}/roles/{role_id}")
        assert await me_permissions() == []

        # 角色权限配置变更同样立即生效：授予后移除角色的一个权限码。
        await request_as(api_client, token, "POST", f"/api/v1/users/{target_id}/roles/{role_id}")
        assert Permissions.USER_VIEW in await me_permissions()
        await request_as(
            api_client,
            token,
            "PUT",
            f"/api/v1/roles/{role_id}/permissions",
            {"permission_codes": [Permissions.USER_VIEW]},  # 移除 USER_LIST，保留 USER_VIEW
        )
        permissions = await me_permissions()
        assert Permissions.USER_LIST not in permissions
        assert Permissions.USER_VIEW in permissions
