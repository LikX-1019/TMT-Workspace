"""Permission catalog contract tests.

The catalog is a development contract: these tests fail the build when an
entry violates the code grammar, references unknown resources, or breaks the
system-role rules, so a malformed definition can never reach a sync.

Phase 3A 起，workspace access permission 由 Workspace Registry 确定性派生并
合并进目录；本测试同时锁定"目录中的 workspace 码与 Registry 完全一致"这一
单一数据源契约。
"""

import re

from app.modules.rbac.catalog import (
    PERMISSION_ACTION_WORDS,
    SUPER_ADMIN_ROLE_CODE,
    SYSTEM_PERMISSIONS,
    SYSTEM_ROLES,
    validate_catalog,
)
from app.modules.rbac.models import DataScopeType, PermissionKind
from app.modules.workspaces.registry import (
    WORKSPACE_REGISTRY,
    workspace_access_permission_code,
)

_CODE_GRAMMAR = re.compile(r"^[a-z][a-z0-9_-]*(:[a-z][a-z0-9_-]*){2}$")

_ACTION_CODES = {
    "system:user:list",
    "system:user:view",
    "system:user:create",
    "system:user:update",
    "system:user:disable",
    "system:department:list",
    "system:department:view",
    "system:department:create",
    "system:department:update",
    "system:department:move",
    "system:department:disable",
    "system:position:list",
    "system:position:view",
    "system:position:create",
    "system:position:update",
    "system:position:disable",
    "system:role:list",
    "system:role:view",
    "system:role:create",
    "system:role:update",
    "system:role:disable",
    "system:role:assign",
    "system:permission:list",
}


def test_catalog_is_self_consistent() -> None:
    assert validate_catalog() == []


def test_action_codes_are_stable() -> None:
    codes = {
        definition.code
        for definition in SYSTEM_PERMISSIONS
        if definition.kind is PermissionKind.ACTION
    }
    assert codes == _ACTION_CODES


def test_workspace_access_codes_match_registry_exactly() -> None:
    """每个 Registry Workspace 恰好派生一个 access code，无重复、无额外。"""

    workspace_definitions = [
        definition
        for definition in SYSTEM_PERMISSIONS
        if definition.kind is PermissionKind.WORKSPACE
    ]
    expected = [workspace_access_permission_code(w.code) for w in WORKSPACE_REGISTRY]
    assert [definition.code for definition in workspace_definitions] == expected
    assert len(workspace_definitions) == len(WORKSPACE_REGISTRY)


def test_workspace_access_definitions_use_workspace_module() -> None:
    for definition in SYSTEM_PERMISSIONS:
        if definition.kind is PermissionKind.WORKSPACE:
            assert definition.module == "workspace"
            assert definition.code.startswith("workspace:")
            assert definition.code.endswith(":access")


def test_catalog_codes_follow_grammar_without_entity_ids() -> None:
    for definition in SYSTEM_PERMISSIONS:
        assert _CODE_GRAMMAR.match(definition.code), definition.code
        for segment in definition.code.split(":"):
            assert not segment.isdigit(), definition.code


def test_catalog_declares_action_and_workspace_kinds_only() -> None:
    """``menu`` kind stays reserved; ``data_scope`` is role policy."""

    assert {definition.kind for definition in SYSTEM_PERMISSIONS} <= {
        PermissionKind.ACTION,
        PermissionKind.WORKSPACE,
    }


def test_modules_match_code_resources() -> None:
    for definition in SYSTEM_PERMISSIONS:
        if definition.kind is PermissionKind.ACTION:
            assert definition.module == definition.code.split(":")[1]


def test_system_roles_reference_known_permissions_only() -> None:
    catalog_codes = {definition.code for definition in SYSTEM_PERMISSIONS}

    for role in SYSTEM_ROLES:
        for code in role.permission_codes or ():
            assert code in catalog_codes


def test_system_roles_receive_no_workspace_access_automatically() -> None:
    """Workspace access 属业务授权：平台 seed 角色不自动获得。"""

    for role in SYSTEM_ROLES:
        for code in role.permission_codes or ():
            assert not code.startswith("workspace:"), (role.code, code)


def test_super_admin_is_dynamic_and_unique_in_that() -> None:
    dynamic = [role for role in SYSTEM_ROLES if role.permission_codes is None]

    assert [role.code for role in dynamic] == [SUPER_ADMIN_ROLE_CODE]
    assert dynamic[0].data_scope_type is DataScopeType.ALL


def test_system_admin_holds_every_action_code() -> None:
    """system_admin 拥有全部 action 权限；workspace access 不在其列。"""

    system_admin = next(role for role in SYSTEM_ROLES if role.code == "system_admin")

    assert system_admin.permission_codes is not None
    assert set(system_admin.permission_codes) == _ACTION_CODES


def test_security_auditor_is_read_only() -> None:
    auditor = next(role for role in SYSTEM_ROLES if role.code == "security_auditor")

    assert auditor.permission_codes is not None
    action_codes = {
        definition.code
        for definition in SYSTEM_PERMISSIONS
        if definition.kind is PermissionKind.ACTION
    }
    assert set(auditor.permission_codes) < action_codes
    for code in auditor.permission_codes:
        assert code.rsplit(":", 1)[-1] in PERMISSION_ACTION_WORDS
