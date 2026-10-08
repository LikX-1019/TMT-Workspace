"""授权强制（require_permission）的完整链路集成测试。

真实链路：FastAPI Dependency + Authentication（401 语义）+
AuthorizationService（有效权限解析）+ PostgreSQL。受保护路由只存在于
测试进程，绝不挂载到 production ``api_router``（见规格第 13 节）。
"""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import pytest
from app.common.responses import SuccessEnvelope, success_response
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import utc_now
from app.main import create_app
from app.modules.auth.models import LocalCredential, RefreshToken
from app.modules.auth.redis_store import RedisAuthStateStore
from app.modules.rbac.catalog import (
    SECURITY_AUDITOR_ROLE_CODE,
    SUPER_ADMIN_ROLE_CODE,
    SYSTEM_ADMIN_ROLE_CODE,
    Permissions,
)
from app.modules.rbac.dependencies import AuthorizationContext, require_permission
from app.modules.rbac.models import PermissionStatus, RoleStatus
from app.modules.rbac.repository import (
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
)
from app.modules.rbac.service import AuthorizationService, PermissionCatalogService
from app.modules.users.models import AccountStatus, EmploymentStatus, User
from asgi_lifespan import LifespanManager
from fastapi import APIRouter, Depends
from httpx import ASGITransport, AsyncClient, Response
from redis import asyncio as redis_asyncio
from redis.asyncio import Redis
from sqlalchemy import make_url, select

from tests.integration.conftest import (
    committed_session,
    create_isolated_engine,
    isolated_database_url,
)

pytestmark = pytest.mark.postgres

PASSWORD = "Authz-Matrix-Passphrase!"
PROTECTED_PATH = "/test/protected-user-list"  # 要求 Permissions.USER_LIST
DENIED_PATH = "/test/protected-user-disable"  # 要求 Permissions.USER_DISABLE


def build_protected_test_router() -> APIRouter:
    """构建仅存在于测试进程的受保护路由（Phase 2B 规格：不留假生产端点）。"""

    router = APIRouter()

    @router.get(PROTECTED_PATH)
    async def protected_user_list(
        context: Annotated[
            AuthorizationContext, Depends(require_permission(Permissions.USER_LIST))
        ],
    ) -> SuccessEnvelope[dict[str, object]]:
        return success_response(
            {"user_id": str(context.user_id), "role_codes": list(context.role_codes)}
        )

    @router.get(DENIED_PATH)
    async def protected_user_disable(
        context: Annotated[
            AuthorizationContext, Depends(require_permission(Permissions.USER_DISABLE))
        ],
    ) -> SuccessEnvelope[dict[str, object]]:
        return success_response({"user_id": str(context.user_id)})

    @router.get("/test/protected-double-check")
    async def protected_double_check(
        first: Annotated[AuthorizationContext, Depends(require_permission(Permissions.USER_LIST))],
        second: Annotated[AuthorizationContext, Depends(require_permission(Permissions.USER_VIEW))],
    ) -> SuccessEnvelope[dict[str, object]]:
        # FastAPI Depends 缓存：同一请求内两个权限检查必须共享同一个 context。
        return success_response({"single_resolution": first is second})

    return router


@pytest.fixture(autouse=True)
async def clean_redis_state(redis_client: Redis) -> None:
    """隔离登录失败计数与会话吊销残留。"""

    return


@pytest.fixture
async def protected_client() -> AsyncIterator[AsyncClient]:
    """绑定 freshly reset 数据库、携带 test-only 路由的 HTTP 客户端。"""

    engine = await create_isolated_engine()
    await engine.dispose()
    application_database = make_url(get_settings().database_url).database
    if application_database != make_url(isolated_database_url()).database:
        pytest.fail(
            "TMT_DATABASE_URL must point at the guarded test database for API tests; "
            f"got {application_database!r}."
        )

    application = create_app()
    application.include_router(build_protected_test_router())
    async with LifespanManager(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def sync_catalog() -> None:
    """把权限目录同步进真实数据库（幂等，毫秒级）。"""

    async with committed_session() as session:
        await PermissionCatalogService(session).sync()
        await session.commit()


async def seed_user(
    username: str,
    *,
    password: str = PASSWORD,
    account_status: str = "active",
    employment_status: str = "active",
) -> UUID:
    """创建带本地凭据、真实提交的用户，返回 user_id。"""

    async with committed_session() as session:
        user = User(
            employee_no=f"E-{username}"[:32],
            username=username,
            name=username.title(),
            email=f"{username}@example.com",
            employment_status=EmploymentStatus(employment_status),
            account_status=AccountStatus(account_status),
        )
        session.add(user)
        await session.flush()
        session.add(
            LocalCredential(
                user_id=user.id,
                password_hash=hash_password(password),
                password_changed_at=utc_now(),
            )
        )
        await session.commit()
        return user.id


async def grant_role(user_id: UUID, role_code: str) -> None:
    async with committed_session() as session:
        await AuthorizationService(session).assign_role(user_id, role_code)
        await session.commit()


async def revoke_role(user_id: UUID, role_code: str) -> None:
    async with committed_session() as session:
        await AuthorizationService(session).remove_role(user_id, role_code)
        await session.commit()


async def set_role_row(
    role_code: str,
    *,
    status: RoleStatus | None = None,
    deleted: bool = False,
) -> None:
    """直接修改角色行数据。

    系统角色禁止走 ``RoleService`` 的 disable/delete；这里从数据面直接改行，
    证明依赖消费的是解析器对**最终数据状态**的结果，而不是 service 守卫。
    """

    async with committed_session() as session:
        role = await RoleRepository(session).get_by_code(role_code, include_deleted=True)
        assert role is not None
        if deleted:
            role.deleted_at = utc_now()
            role.status = RoleStatus.DISABLED
        elif status is not None:
            role.status = status
        await session.commit()


async def set_permission_state(code: str, status: PermissionStatus) -> None:
    async with committed_session() as session:
        permission = await PermissionRepository(session).get_by_code(code)
        assert permission is not None
        permission.status = status
        await session.commit()


async def set_grant(role_code: str, permission_code: str, *, present: bool) -> None:
    async with committed_session() as session:
        role = await RoleRepository(session).get_by_code(role_code)
        permission = await PermissionRepository(session).get_by_code(permission_code)
        assert role is not None
        assert permission is not None
        grants = RolePermissionRepository(session)
        if present:
            await grants.assign(role.id, permission.id)
        else:
            await grants.remove(role.id, permission.id)
        await session.commit()


async def set_user_state(
    username: str,
    *,
    account_status: str | None = None,
    employment_status: str | None = None,
) -> None:
    async with committed_session() as session:
        user = await session.scalar(select(User).where(User.username == username))
        assert user is not None
        if account_status is not None:
            user.account_status = AccountStatus(account_status)
        if employment_status is not None:
            user.employment_status = EmploymentStatus(employment_status)
        await session.commit()


async def latest_session_id(username: str) -> UUID:
    """取该用户最近一次登录的 session_id（用于真实吊销）。"""

    async with committed_session() as session:
        user = await session.scalar(select(User).where(User.username == username))
        assert user is not None
        token = await session.scalar(
            select(RefreshToken)
            .where(RefreshToken.user_id == user.id)
            .order_by(RefreshToken.created_at.desc())
        )
        assert token is not None
        return token.session_id


async def login_access_token(client: AsyncClient, username: str, password: str = PASSWORD) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["access_token"]


async def get_protected(client: AsyncClient, token: str | None = None) -> Response:
    """访问受保护端点；token 为 None 时模拟未认证请求。"""

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return await client.get(PROTECTED_PATH, headers=headers)


class TestAuthenticationBoundary:
    """401 语义：认证失败先于授权判定，require_permission 不得捕获改写。"""

    async def test_case_01_missing_token_is_401(self, protected_client: AsyncClient) -> None:
        await sync_catalog()

        response = await get_protected(protected_client)

        assert response.status_code == 401
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "AUTHENTICATION_FAILED"

    async def test_case_13_disabled_user_is_401(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "case13-disabled"
        await seed_user(username)
        token = await login_access_token(protected_client, username)
        await set_user_state(username, account_status="disabled")

        response = await get_protected(protected_client, token)

        assert response.status_code == 401

    async def test_case_14_resigned_user_is_401(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "case14-resigned"
        await seed_user(username)
        token = await login_access_token(protected_client, username)
        await set_user_state(username, employment_status="resigned")

        response = await get_protected(protected_client, token)

        assert response.status_code == 401

    async def test_case_15_revoked_session_is_401(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "case15-revoked"
        await seed_user(username)
        token = await login_access_token(protected_client, username)
        session_id = await latest_session_id(username)
        store = RedisAuthStateStore(
            redis_asyncio.from_url(get_settings().redis_url, decode_responses=True)
        )
        await store.revoke_session(session_id, ttl_seconds=60)

        response = await get_protected(protected_client, token)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "SESSION_REVOKED"


class TestAuthorizationMatrix:
    """403 / 200 矩阵：权限判定完全由 AuthorizationService 的有效结果决定。"""

    async def test_case_02_user_without_roles_is_403(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "case02-no-roles"
        await seed_user(username)
        token = await login_access_token(protected_client, username)

        response = await get_protected(protected_client, token)

        assert response.status_code == 403
        body = response.json()
        assert body["error"]["code"] == "AUTHORIZATION_FAILED"
        assert body["error"]["details"] == {}
        assert "system:user:list" not in response.text  # 不回显 required permission

    async def test_case_03_role_without_permission_is_403(
        self, protected_client: AsyncClient
    ) -> None:
        await sync_catalog()
        username = "case03-wrong-perm"
        user_id = await seed_user(username)
        await grant_role(user_id, SECURITY_AUDITOR_ROLE_CODE)  # 只有 list/view
        token = await login_access_token(protected_client, username)

        # auditor 没有 system:user:disable -> 403。
        response = await protected_client.get(
            DENIED_PATH, headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 403

    async def test_case_04_role_with_permission_is_200(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "case04-allowed"
        user_id = await seed_user(username)
        await grant_role(user_id, SECURITY_AUDITOR_ROLE_CODE)
        token = await login_access_token(protected_client, username)

        response = await get_protected(protected_client, token)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["role_codes"] == [SECURITY_AUDITOR_ROLE_CODE]

    async def test_case_05_union_across_roles_is_200(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "case05-union"
        user_id = await seed_user(username)
        await grant_role(user_id, SECURITY_AUDITOR_ROLE_CODE)
        await grant_role(user_id, SYSTEM_ADMIN_ROLE_CODE)
        token = await login_access_token(protected_client, username)

        response = await get_protected(protected_client, token)

        assert response.status_code == 200
        data = response.json()["data"]
        assert set(data["role_codes"]) == {SECURITY_AUDITOR_ROLE_CODE, SYSTEM_ADMIN_ROLE_CODE}

    async def test_case_06_disabled_role_is_403(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "case06-frozen-role"
        user_id = await seed_user(username)
        await grant_role(user_id, SECURITY_AUDITOR_ROLE_CODE)
        token = await login_access_token(protected_client, username)
        await set_role_row(SECURITY_AUDITOR_ROLE_CODE, status=RoleStatus.DISABLED)

        response = await get_protected(protected_client, token)

        assert response.status_code == 403

    async def test_case_07_soft_deleted_role_is_403(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "case07-deleted-role"
        user_id = await seed_user(username)
        await grant_role(user_id, SECURITY_AUDITOR_ROLE_CODE)
        token = await login_access_token(protected_client, username)
        await set_role_row(SECURITY_AUDITOR_ROLE_CODE, deleted=True)

        response = await get_protected(protected_client, token)

        assert response.status_code == 403

    async def test_case_08_disabled_permission_is_403(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "case08-dead-perm"
        user_id = await seed_user(username)
        await grant_role(user_id, SECURITY_AUDITOR_ROLE_CODE)
        token = await login_access_token(protected_client, username)
        await set_permission_state(Permissions.USER_LIST, PermissionStatus.DISABLED)

        response = await get_protected(protected_client, token)

        assert response.status_code == 403

    async def test_case_09_removed_role_permission_is_403(
        self, protected_client: AsyncClient
    ) -> None:
        await sync_catalog()
        username = "case09-cut-grant"
        user_id = await seed_user(username)
        await grant_role(user_id, SECURITY_AUDITOR_ROLE_CODE)
        token = await login_access_token(protected_client, username)
        await set_grant(SECURITY_AUDITOR_ROLE_CODE, Permissions.USER_LIST, present=False)

        response = await get_protected(protected_client, token)

        assert response.status_code == 403

    async def test_case_10_removed_user_role_is_403(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "case10-cut-role"
        user_id = await seed_user(username)
        await grant_role(user_id, SECURITY_AUDITOR_ROLE_CODE)
        token = await login_access_token(protected_client, username)
        await revoke_role(user_id, SECURITY_AUDITOR_ROLE_CODE)

        response = await get_protected(protected_client, token)

        assert response.status_code == 403

    async def test_case_11_super_admin_is_dynamic_200(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "case11-super"
        user_id = await seed_user(username)
        await grant_role(user_id, SUPER_ADMIN_ROLE_CODE)  # 无任何显式 grant
        token = await login_access_token(protected_client, username)

        response = await get_protected(protected_client, token)

        assert response.status_code == 200

    async def test_case_12_admin_username_without_role_is_403(
        self, protected_client: AsyncClient
    ) -> None:
        await sync_catalog()
        username = "admin"  # 用户名叫 admin 不构成任何授权
        await seed_user(username)
        token = await login_access_token(protected_client, username)

        response = await get_protected(protected_client, token)

        assert response.status_code == 403


class TestImmediateEffect:
    """无缓存契约：授权数据变更后，下一请求立即生效（规格第 15 节）。"""

    async def test_grant_revoke_regrant_cycle(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "cycle-grant"
        user_id = await seed_user(username)
        await grant_role(user_id, SECURITY_AUDITOR_ROLE_CODE)
        token = await login_access_token(protected_client, username)

        assert (await get_protected(protected_client, token)).status_code == 200
        await set_grant(SECURITY_AUDITOR_ROLE_CODE, Permissions.USER_LIST, present=False)
        assert (await get_protected(protected_client, token)).status_code == 403
        await set_grant(SECURITY_AUDITOR_ROLE_CODE, Permissions.USER_LIST, present=True)
        assert (await get_protected(protected_client, token)).status_code == 200

    async def test_role_disable_reenable_cycle(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "cycle-role"
        user_id = await seed_user(username)
        await grant_role(user_id, SECURITY_AUDITOR_ROLE_CODE)
        token = await login_access_token(protected_client, username)

        await set_role_row(SECURITY_AUDITOR_ROLE_CODE, status=RoleStatus.DISABLED)
        assert (await get_protected(protected_client, token)).status_code == 403
        await set_role_row(SECURITY_AUDITOR_ROLE_CODE, status=RoleStatus.ACTIVE)
        assert (await get_protected(protected_client, token)).status_code == 200

    async def test_permission_disable_reenable_cycle(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "cycle-perm"
        user_id = await seed_user(username)
        await grant_role(user_id, SECURITY_AUDITOR_ROLE_CODE)
        token = await login_access_token(protected_client, username)

        await set_permission_state(Permissions.USER_LIST, PermissionStatus.DISABLED)
        assert (await get_protected(protected_client, token)).status_code == 403
        await set_permission_state(Permissions.USER_LIST, PermissionStatus.ACTIVE)
        assert (await get_protected(protected_client, token)).status_code == 200


class TestContextReuse:
    """同一请求内多个权限检查共享一次解析（FastAPI Depends 缓存）。"""

    async def test_double_check_shares_one_context(self, protected_client: AsyncClient) -> None:
        await sync_catalog()
        username = "ctx-reuse"
        user_id = await seed_user(username)
        await grant_role(user_id, SECURITY_AUDITOR_ROLE_CODE)
        token = await login_access_token(protected_client, username)

        response = await protected_client.get(
            "/test/protected-double-check",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json()["data"]["single_resolution"] is True


class TestDeniedEvidence:
    """拒绝时的日志与响应契约。"""

    async def test_denial_does_not_leak_required_permission(
        self,
        protected_client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        await sync_catalog()
        username = "deny-log"
        await seed_user(username)
        token = await login_access_token(protected_client, username)

        with caplog.at_level("WARNING", logger="app.modules.rbac.dependencies"):
            response = await get_protected(protected_client, token)

        assert response.status_code == 403
        # 响应体不含权限码与授权结构；日志侧记录了审计要素。
        assert "system:user:list" not in response.text
        denial_logs = [record for record in caplog.records if "授权拒绝" in record.message]
        assert denial_logs, "拒绝事件应写入日志"
