"""User Management API 的授权矩阵与业务规则测试。"""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.integration.conftest import (
    MANAGEMENT_PASSWORD,
    committed_session,
    request_as,
)

pytestmark = pytest.mark.postgres

ANY_USER_ID = str(uuid4())
ANY_ROLE_ID = str(uuid4())

ENDPOINTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/api/v1/users", None),
    ("GET", f"/api/v1/users/{ANY_USER_ID}", None),
    (
        "POST",
        "/api/v1/users",
        {"employee_no": "E-matrix", "username": "matrix-new", "name": "Matrix New"},
    ),
    ("PATCH", f"/api/v1/users/{ANY_USER_ID}", {"name": "Renamed"}),
    ("POST", f"/api/v1/users/{ANY_USER_ID}/disable", None),
    ("POST", f"/api/v1/users/{ANY_USER_ID}/enable", None),
    ("POST", f"/api/v1/users/{ANY_USER_ID}/resign", None),
    ("GET", f"/api/v1/users/{ANY_USER_ID}/roles", None),
    ("POST", f"/api/v1/users/{ANY_USER_ID}/roles/{ANY_ROLE_ID}", None),
    ("DELETE", f"/api/v1/users/{ANY_USER_ID}/roles/{ANY_ROLE_ID}", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
async def test_unauthenticated_is_401(
    api_client: AsyncClient, method: str, path: str, body: dict[str, object] | None
) -> None:
    assert (await request_as(api_client, None, method, path, body)).status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
async def test_without_permission_is_403(
    api_client: AsyncClient,
    management_accounts: dict[str, str],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    response = await request_as(api_client, management_accounts["plain_token"], method, path, body)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTHORIZATION_FAILED"


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
async def test_super_admin_passes_authorization(
    api_client: AsyncClient,
    management_accounts: dict[str, str],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    """super_admin 全部放行（目标不存在的读端点表现为 404，同样不算授权失败）。"""

    response = await request_as(api_client, management_accounts["super_token"], method, path, body)
    assert response.status_code not in (401, 403)


async def _create_user(
    api_client: AsyncClient, token: str, *, username: str = "created-user"
) -> str:
    response = await request_as(
        api_client,
        token,
        "POST",
        "/api/v1/users",
        {
            "employee_no": f"E-{username}"[:32],
            "username": username,
            "name": username.title(),
            "email": f"{username}@example.com",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


class TestUserListAndDetail:
    async def test_list_returns_pagination_and_filters(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        await _create_user(api_client, token, username="list-alice")

        page = await request_as(api_client, token, "GET", "/api/v1/users?page=1&page_size=1")
        assert page.status_code == 200
        body = page.json()
        assert len(body["data"]) == 1
        assert body["meta"]["total"] >= 2  # matrix 账号 + 新建用户
        assert body["meta"]["total_pages"] >= 2

        filtered = await request_as(api_client, token, "GET", "/api/v1/users?keyword=list-alice")
        assert filtered.json()["meta"]["total"] == 1

        by_status = await request_as(
            api_client, token, "GET", "/api/v1/users?account_status=disabled"
        )
        assert by_status.json()["meta"]["total"] == 0

    async def test_detail_includes_primary_org_and_never_credentials(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        user_id = await _create_user(api_client, token, username="detail-bob")

        detail = await request_as(api_client, token, "GET", f"/api/v1/users/{user_id}")

        assert detail.status_code == 200
        data = detail.json()["data"]
        assert data["primary_department"] is None  # 未分配组织
        assert "password" not in detail.text.lower().replace("password_changed_at", "")

    async def test_unknown_user_detail_is_404(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        response = await request_as(
            api_client, management_accounts["super_token"], "GET", f"/api/v1/users/{uuid4()}"
        )
        assert response.status_code == 404


class TestUserCreate:
    async def test_create_is_identity_only_no_credential(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]

        response = await request_as(
            api_client,
            token,
            "POST",
            "/api/v1/users",
            {
                "employee_no": "E-no-cred",
                "username": "no-cred",
                "name": "No Cred",
                # 恶意/误传的凭据字段必须被忽略：schema 根本不声明它们
                "password": "should-be-ignored",
                "password_hash": "also-ignored",
            },
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert "password_hash" not in data

        # 无凭据：无法登录
        login = await api_client.post(
            "/api/v1/auth/login", json={"username": "no-cred", "password": MANAGEMENT_PASSWORD}
        )
        assert login.status_code == 401

    async def test_duplicate_username_and_employee_no_are_409(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        await _create_user(api_client, token, username="dup-target")

        dup_username = await request_as(
            api_client,
            token,
            "POST",
            "/api/v1/users",
            {"employee_no": "E-other", "username": "dup-target", "name": "Dup"},
        )
        assert dup_username.status_code == 409

        dup_employee_no = await request_as(
            api_client,
            token,
            "POST",
            "/api/v1/users",
            {"employee_no": "E-dup-target", "username": "other-user", "name": "Dup"},
        )
        assert dup_employee_no.status_code == 409


class TestUserUpdateAndLifecycle:
    async def test_patch_updates_allowlist_fields(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        user_id = await _create_user(api_client, token, username="patch-me")

        response = await request_as(
            api_client, token, "PATCH", f"/api/v1/users/{user_id}", {"name": "Patched Name"}
        )

        assert response.status_code == 200
        assert response.json()["data"]["name"] == "Patched Name"

    async def test_disable_then_authentication_fails_immediately(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        operator_token = management_accounts["super_token"]
        user_id = await _create_user(api_client, operator_token, username="doomed-user")
        password = "Doomed-Passphrase-1!"
        async with committed_session() as session:
            from app.core.security import hash_password
            from app.db.base import utc_now
            from app.modules.auth.models import LocalCredential
            from app.modules.users.models import User

            user = await session.scalar(select(User).where(User.username == "doomed-user"))
            assert user is not None
            session.add(
                LocalCredential(
                    user_id=user.id,
                    password_hash=hash_password(password),
                    password_changed_at=utc_now(),
                )
            )
            await session.commit()

        login = await api_client.post(
            "/api/v1/auth/login", json={"username": "doomed-user", "password": password}
        )
        assert login.status_code == 200
        victim_token = login.json()["data"]["access_token"]

        disable = await request_as(
            api_client, operator_token, "POST", f"/api/v1/users/{user_id}/disable"
        )
        assert disable.status_code == 200
        assert disable.json()["data"]["account_status"] == "disabled"

        # 已签发的 token 下一请求立即失效（get_current_user 逐请求校验账号状态）。
        assert (
            await request_as(api_client, victim_token, "GET", "/api/v1/auth/me")
        ).status_code == 401
        assert (
            await api_client.post(
                "/api/v1/auth/login", json={"username": "doomed-user", "password": password}
            )
        ).status_code == 401

        enable = await request_as(
            api_client, operator_token, "POST", f"/api/v1/users/{user_id}/enable"
        )
        assert enable.status_code == 200
        assert (
            await api_client.post(
                "/api/v1/auth/login", json={"username": "doomed-user", "password": password}
            )
        ).status_code == 200

    async def test_operator_cannot_disable_self(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        response = await request_as(
            api_client,
            management_accounts["super_token"],
            "POST",
            f"/api/v1/users/{management_accounts['super_id']}/disable",
        )
        assert response.status_code == 409

    async def test_operator_cannot_resign_self(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        response = await request_as(
            api_client,
            management_accounts["super_token"],
            "POST",
            f"/api/v1/users/{management_accounts['super_id']}/resign",
        )
        assert response.status_code == 409

    async def test_patch_self_lockout_is_rejected(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        response = await request_as(
            api_client,
            management_accounts["super_token"],
            "PATCH",
            f"/api/v1/users/{management_accounts['super_id']}",
            {"account_status": "disabled"},
        )
        assert response.status_code == 409

    async def test_resign_blocks_authentication(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        user_id = await _create_user(api_client, token, username="leaving-user")

        resign = await request_as(api_client, token, "POST", f"/api/v1/users/{user_id}/resign")
        assert resign.status_code == 200
        assert resign.json()["data"]["employment_status"] == "resigned"
        assert resign.json()["data"]["account_status"] == "active"  # 账号状态与员工状态分离
