"""Workspace registry contract tests.

The registry is a code-owned definition of which workspaces may exist; these
tests fail the build when a definition is malformed or drifts from the
permission catalog derivation.
"""

from pathlib import Path

from app.modules.rbac.catalog import CATALOG_PERMISSION_CODES, SYSTEM_PERMISSIONS
from app.modules.rbac.models import PermissionKind
from app.modules.workspaces.registry import (
    WORKSPACE_REGISTRY,
    validate_workspace_registry,
    workspace_access_permission_code,
)


def test_registry_is_self_consistent() -> None:
    assert validate_workspace_registry() == []


def test_registry_codes_are_unique_and_stable_grammar() -> None:
    codes = [definition.code for definition in WORKSPACE_REGISTRY]
    assert len(codes) == len(set(codes))
    for code in codes:
        assert code == code.lower()
        assert code.replace("-", "").isalnum()
        assert not code.startswith("-")
        assert not code.endswith("-")


def test_registry_matches_frontend_workspace_directories() -> None:
    """Registry 与前端 canonical 目录一一对应（单一事实源）。"""

    frontend_root = Path(__file__).resolve().parents[2] / "frontend/src/workspaces"
    directories = {
        path.name
        for path in frontend_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }
    assert directories == {definition.code for definition in WORKSPACE_REGISTRY}


def test_every_registry_workspace_has_exactly_one_access_permission() -> None:
    for definition in WORKSPACE_REGISTRY:
        access_code = workspace_access_permission_code(definition.code)
        matches = [entry for entry in SYSTEM_PERMISSIONS if entry.code == access_code]
        assert len(matches) == 1, definition.code
        assert matches[0].kind is PermissionKind.WORKSPACE
        assert matches[0].module == "workspace"


def test_access_codes_are_part_of_the_catalog() -> None:
    expected = {workspace_access_permission_code(d.code) for d in WORKSPACE_REGISTRY}
    assert expected <= CATALOG_PERMISSION_CODES


def test_system_management_is_never_a_business_workspace() -> None:
    codes = {definition.code for definition in WORKSPACE_REGISTRY}
    assert "system" not in codes
    assert "admin" not in codes
    assert "public" not in codes  # 尚无产品消费者，不得预先注册
