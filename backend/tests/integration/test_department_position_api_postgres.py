"""Department / Position Management API 的授权矩阵与业务规则测试。"""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.integration.conftest import committed_session, request_as

pytestmark = pytest.mark.postgres

ANY_ID = str(uuid4())

DEPARTMENT_ENDPOINTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/api/v1/departments", None),
    ("GET", "/api/v1/departments/tree", None),
    ("GET", f"/api/v1/departments/{ANY_ID}", None),
    ("POST", "/api/v1/departments", {"name": "Matrix Dept", "code": "matrix-dept"}),
    ("PATCH", f"/api/v1/departments/{ANY_ID}", {"name": "Renamed"}),
    ("POST", f"/api/v1/departments/{ANY_ID}/move", {"new_parent_id": None}),
    ("POST", f"/api/v1/departments/{ANY_ID}/disable", None),
    ("POST", f"/api/v1/departments/{ANY_ID}/enable", None),
]

POSITION_ENDPOINTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/api/v1/positions", None),
    ("GET", f"/api/v1/positions/{ANY_ID}", None),
    ("POST", "/api/v1/positions", {"name": "Matrix Position", "code": "matrix-position"}),
    ("PATCH", f"/api/v1/positions/{ANY_ID}", {"name": "Renamed"}),
    ("POST", f"/api/v1/positions/{ANY_ID}/disable", None),
    ("POST", f"/api/v1/positions/{ANY_ID}/enable", None),
]


@pytest.mark.parametrize(("method", "path", "body"), DEPARTMENT_ENDPOINTS)
async def test_department_unauthenticated_is_401(
    api_client: AsyncClient, method: str, path: str, body: dict[str, object] | None
) -> None:
    assert (await request_as(api_client, None, method, path, body)).status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), DEPARTMENT_ENDPOINTS)
async def test_department_without_permission_is_403(
    api_client: AsyncClient,
    management_accounts: dict[str, str],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    response = await request_as(api_client, management_accounts["plain_token"], method, path, body)
    assert response.status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), DEPARTMENT_ENDPOINTS)
async def test_department_super_admin_allowed(
    api_client: AsyncClient,
    management_accounts: dict[str, str],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    response = await request_as(api_client, management_accounts["super_token"], method, path, body)
    assert response.status_code not in (401, 403)


@pytest.mark.parametrize(("method", "path", "body"), POSITION_ENDPOINTS)
async def test_position_unauthenticated_is_401(
    api_client: AsyncClient, method: str, path: str, body: dict[str, object] | None
) -> None:
    assert (await request_as(api_client, None, method, path, body)).status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), POSITION_ENDPOINTS)
async def test_position_without_permission_is_403(
    api_client: AsyncClient,
    management_accounts: dict[str, str],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    response = await request_as(api_client, management_accounts["plain_token"], method, path, body)
    assert response.status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), POSITION_ENDPOINTS)
async def test_position_super_admin_allowed(
    api_client: AsyncClient,
    management_accounts: dict[str, str],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    response = await request_as(api_client, management_accounts["super_token"], method, path, body)
    assert response.status_code not in (401, 403)


async def _create_department(
    api_client: AsyncClient,
    token: str,
    *,
    name: str,
    code: str,
    parent_id: str | None = None,
) -> str:
    response = await request_as(
        api_client,
        token,
        "POST",
        "/api/v1/departments",
        {"name": name, "code": code, "parent_id": parent_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


class TestDepartmentRules:
    async def test_create_root_and_child_tree_structure(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        root_id = await _create_department(api_client, token, name="Engineering", code="eng")
        child_id = await _create_department(
            api_client, token, name="Platform", code="eng-platform", parent_id=root_id
        )

        tree = await request_as(api_client, token, "GET", "/api/v1/departments/tree")
        assert tree.status_code == 200
        nodes = tree.json()["data"]
        assert len(nodes) == 1  # 单根
        assert nodes[0]["id"] == root_id
        assert [child["id"] for child in nodes[0]["children"]] == [child_id]

    async def test_duplicate_code_is_409(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        await _create_department(api_client, token, name="First", code="same-code")

        duplicate = await request_as(
            api_client,
            token,
            "POST",
            "/api/v1/departments",
            {"name": "Second", "code": "same-code"},
        )
        assert duplicate.status_code == 409

    async def test_move_rejects_self_parent(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        dept_id = await _create_department(api_client, token, name="Self", code="self-parent")

        response = await request_as(
            api_client,
            token,
            "POST",
            f"/api/v1/departments/{dept_id}/move",
            {"new_parent_id": dept_id},
        )
        assert response.status_code == 422

    async def test_move_rejects_descendant_target(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        root_id = await _create_department(api_client, token, name="Root", code="move-root")
        child_id = await _create_department(
            api_client, token, name="Child", code="move-child", parent_id=root_id
        )
        grandchild_id = await _create_department(
            api_client, token, name="Grandchild", code="move-grandchild", parent_id=child_id
        )

        response = await request_as(
            api_client,
            token,
            "POST",
            f"/api/v1/departments/{root_id}/move",
            {"new_parent_id": grandchild_id},
        )
        assert response.status_code == 422

    async def test_move_to_unrelated_parent_succeeds(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        root_a = await _create_department(api_client, token, name="A", code="move-a")
        root_b = await _create_department(api_client, token, name="B", code="move-b")
        child = await _create_department(
            api_client, token, name="A-Child", code="move-a-child", parent_id=root_a
        )

        moved = await request_as(
            api_client,
            token,
            "POST",
            f"/api/v1/departments/{child}/move",
            {"new_parent_id": root_b},
        )

        assert moved.status_code == 200
        assert moved.json()["data"]["parent_id"] == root_b

    async def test_disable_then_enable_round_trip(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        dept_id = await _create_department(api_client, token, name="Cycle", code="cycle-dept")

        disabled = await request_as(
            api_client, token, "POST", f"/api/v1/departments/{dept_id}/disable"
        )
        assert disabled.json()["data"]["status"] == "disabled"

        # disabled 部门不参与普通 tree。
        tree = await request_as(api_client, token, "GET", "/api/v1/departments/tree")
        assert tree.json()["data"] == []

        enabled = await request_as(
            api_client, token, "POST", f"/api/v1/departments/{dept_id}/enable"
        )
        assert enabled.json()["data"]["status"] == "active"
        tree = await request_as(api_client, token, "GET", "/api/v1/departments/tree")
        assert len(tree.json()["data"]) == 1

    async def test_leader_must_be_existing_user(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        from uuid import UUID

        token = management_accounts["super_token"]
        leader_id = management_accounts["super_id"]

        ok = await request_as(
            api_client,
            token,
            "POST",
            "/api/v1/departments",
            {"name": "Led", "code": "led-dept", "leader_id": leader_id},
        )
        assert ok.status_code == 201
        assert ok.json()["data"]["leader_id"] == leader_id

        ghost = await request_as(
            api_client,
            token,
            "POST",
            "/api/v1/departments",
            {"name": "Ghost", "code": "ghost-dept", "leader_id": str(UUID(int=0))},
        )
        assert ghost.status_code == 404


class TestPositionRules:
    async def test_create_update_disable_enable(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]

        created = await request_as(
            api_client,
            token,
            "POST",
            "/api/v1/positions",
            {"name": "Engineer", "code": "engineer"},
        )
        assert created.status_code == 201
        position_id = created.json()["data"]["id"]

        updated = await request_as(
            api_client, token, "PATCH", f"/api/v1/positions/{position_id}", {"name": "Senior"}
        )
        assert updated.json()["data"]["name"] == "Senior"

        disabled = await request_as(
            api_client, token, "POST", f"/api/v1/positions/{position_id}/disable"
        )
        assert disabled.json()["data"]["status"] == "disabled"

        listing = await request_as(api_client, token, "GET", "/api/v1/positions")
        assert listing.json()["data"][0]["status"] == "disabled"

        enabled = await request_as(
            api_client, token, "POST", f"/api/v1/positions/{position_id}/enable"
        )
        assert enabled.json()["data"]["status"] == "active"

    async def test_duplicate_code_is_409(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        token = management_accounts["super_token"]
        payload = {"name": "Same", "code": "same-position"}

        assert (
            await request_as(api_client, token, "POST", "/api/v1/positions", payload)
        ).status_code == 201
        assert (
            await request_as(api_client, token, "POST", "/api/v1/positions", payload)
        ).status_code == 409

    async def test_position_operations_never_touch_roles(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        """Position 是组织岗位：全程不得产生任何 Role/Permission 副作用。"""

        from tests.integration.conftest import committed_session

        token = management_accounts["super_token"]
        async with committed_session() as session:
            from app.modules.rbac.models import Role
            from sqlalchemy import func, select

            before = await session.scalar(select(func.count()).select_from(Role))

        await request_as(
            api_client,
            token,
            "POST",
            "/api/v1/positions",
            {"name": "Director", "code": "director"},
        )
        listing = await request_as(api_client, token, "GET", "/api/v1/positions")
        position_id = listing.json()["data"][0]["id"]
        await request_as(api_client, token, "POST", f"/api/v1/positions/{position_id}/disable")

        async with committed_session() as session:
            from app.modules.rbac.models import Role
            from sqlalchemy import func, select

            after = await session.scalar(select(func.count()).select_from(Role))

        assert before == after

    async def test_department_filter_is_query_condition_not_data_scope(
        self, api_client: AsyncClient, management_accounts: dict[str, str]
    ) -> None:
        """department 过滤是管理员查询条件；拥有 list 权限即查全量（Phase 2C 边界）。"""

        token = management_accounts["super_token"]
        dept_id = await _create_department(api_client, token, name="Scoped", code="scoped-dept")
        await _create_user_with_department(api_client, token, "scoped-user", dept_id)
        await _create_user_with_department(api_client, token, "other-user", None)

        response = await request_as(
            api_client, token, "GET", f"/api/v1/users?department_id={dept_id}"
        )
        usernames = {user["username"] for user in response.json()["data"]}
        assert usernames == {"scoped-user"}


async def _create_user_with_department(
    api_client: AsyncClient, token: str, username: str, department_id: str | None
) -> None:
    from tests.integration.conftest import committed_session

    created = await request_as(
        api_client,
        token,
        "POST",
        "/api/v1/users",
        {"employee_no": f"E-{username}"[:32], "username": username, "name": username.title()},
    )
    user_id = created.json()["data"]["id"]
    if department_id is None:
        return
    async with committed_session() as session:
        from uuid import UUID

        from app.modules.users.models import UserDepartment

        session.add(
            UserDepartment(
                user_id=UUID(user_id), department_id=UUID(department_id), is_primary=True
            )
        )
        await session.commit()


# 用户域的 detail 视图断言补充：主部门/主职位摘要。
async def test_user_detail_shows_primary_org(
    api_client: AsyncClient, management_accounts: dict[str, str]
) -> None:
    token = management_accounts["super_token"]
    dept_id = await _create_department(api_client, token, name="Detail", code="detail-dept")
    user_id = str(uuid4())
    created = await request_as(
        api_client,
        token,
        "POST",
        "/api/v1/users",
        {"employee_no": "E-detail-user", "username": "detail-user", "name": "Detail User"},
    )
    user_id = created.json()["data"]["id"]
    async with committed_session() as session:
        from uuid import UUID

        from app.modules.users.models import UserDepartment

        session.add(
            UserDepartment(user_id=UUID(user_id), department_id=UUID(dept_id), is_primary=True)
        )
        await session.commit()

    detail = await request_as(api_client, token, "GET", f"/api/v1/users/{user_id}")
    assert detail.json()["data"]["primary_department"]["code"] == "detail-dept"
