"""Workspace/menu DTO boundaries.

These schemas define the future API contract shape. Phase 3A exposes no HTTP
management or navigation endpoints; services and tests consume these DTOs so
a later phase can mount routes without redesigning the boundary.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceStatusDTO(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class MenuStatusDTO(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class MenuTypeDTO(StrEnum):
    DIRECTORY = "directory"
    PAGE = "page"


class WorkspaceRead(BaseModel):
    """Registry-mirrored workspace: stable code plus operational metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None = None
    icon: str | None = None
    home_path: str | None = None
    sort: int
    status: WorkspaceStatusDTO


class WorkspaceDepartmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workspace_id: UUID
    department_id: UUID


class MenuCreate(BaseModel):
    """菜单创建契约：route_path 为 workspace 内相对路径，禁止绝对路径。"""

    workspace_id: UUID
    parent_id: UUID | None = None
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    menu_type: MenuTypeDTO
    route_path: str | None = Field(default=None, max_length=256)
    component_key: str | None = Field(default=None, max_length=128)
    icon: str | None = Field(default=None, max_length=128)
    permission_code: str | None = Field(default=None, max_length=128)
    sort: int = 0
    visible: bool = True


class MenuUpdate(BaseModel):
    """菜单更新契约：code/workspace/menu_type 不可变，parent 变更走 move 语义。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    parent_id: UUID | None = None
    route_path: str | None = Field(default=None, max_length=256)
    component_key: str | None = Field(default=None, max_length=128)
    icon: str | None = Field(default=None, max_length=128)
    permission_code: str | None = Field(default=None, max_length=128)
    sort: int | None = None
    visible: bool | None = None


class MenuRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    parent_id: UUID | None
    code: str
    name: str
    menu_type: MenuTypeDTO
    route_path: str | None
    component_key: str | None
    icon: str | None
    permission_code: str | None
    sort: int
    visible: bool
    status: MenuStatusDTO
    created_at: datetime
    updated_at: datetime


class MenuTreeNode(MenuRead):
    """服务端组装的导航树节点（仅 composition 数据，不是授权边界）。"""

    children: list["MenuTreeNode"] = []


class MenuListQuery(BaseModel):
    """菜单查询参数（未来管理/导航 API 复用）。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=100)
    status: MenuStatusDTO | None = None
    parent_id: UUID | None = None
    order: Literal["asc", "desc"] = "asc"


__all__ = [
    "MenuCreate",
    "MenuListQuery",
    "MenuRead",
    "MenuStatusDTO",
    "MenuTreeNode",
    "MenuTypeDTO",
    "MenuUpdate",
    "WorkspaceDepartmentRead",
    "WorkspaceRead",
    "WorkspaceStatusDTO",
]
