"""授权依赖的单元契约测试。

覆盖两件事：

1. ``require_permission`` 对未知权限码 fail fast（编程错误在路由构建阶段
   暴露，绝不演变成上线后所有请求默默 403）；
2. ``Permissions`` 常量表与 ``SYSTEM_PERMISSIONS`` 目录完全一致，防止
   "目录加了条目、常量忘了加"的静默漂移。
"""

from uuid import uuid4

import pytest
from app.modules.rbac.catalog import (
    CATALOG_PERMISSION_CODES,
    SYSTEM_PERMISSIONS,
    Permissions,
)
from app.modules.rbac.dependencies import AuthorizationContext, require_permission
from app.modules.rbac.models import PermissionKind


class TestRequirePermissionConstruction:
    def test_unknown_code_fails_fast(self) -> None:
        with pytest.raises(ValueError, match="system:usr:lsit"):
            require_permission("system:usr:lsit")

    def test_entirely_unknown_code_fails_fast(self) -> None:
        with pytest.raises(ValueError, match="system:not-real:permission"):
            require_permission("system:not-real:permission")

    def test_valid_code_returns_dependency(self) -> None:
        dependency = require_permission(Permissions.USER_LIST)

        assert callable(dependency)

    def test_every_catalog_code_is_accepted(self) -> None:
        for code in sorted(CATALOG_PERMISSION_CODES):
            assert callable(require_permission(code))


class TestPermissionsConstants:
    def test_permissions_constants_match_action_catalog_exactly(self) -> None:
        """Permissions 字符串常量与 action 权限一一对应。

        workspace access 码由 Workspace Registry 单一数据源派生
        （``Permissions.workspace_access(code)``），Phase 3B enforcement 接入时
        仍会经过 ``require_permission`` 的目录 fail-fast 校验，不需要在常量类
        里手工维护第二份列表。
        """

        declared = {
            name: value
            for name, value in vars(Permissions).items()
            if not name.startswith("_") and isinstance(value, str)
        }

        assert set(declared.values()) == {
            definition.code
            for definition in SYSTEM_PERMISSIONS
            if definition.kind is PermissionKind.ACTION
        }
        # workspace access 码必须整体落在目录内（Registry 与目录联动契约）。
        assert {
            definition.code
            for definition in SYSTEM_PERMISSIONS
            if definition.kind is PermissionKind.WORKSPACE
        } <= CATALOG_PERMISSION_CODES


class TestAuthorizationContext:
    def test_has_permission_membership(self) -> None:
        context = AuthorizationContext(
            user_id=uuid4(),
            role_codes=("security_auditor",),
            permission_codes=frozenset({"system:user:list", "system:user:view"}),
        )

        assert context.has_permission("system:user:list") is True
        assert context.has_permission("system:user:create") is False
