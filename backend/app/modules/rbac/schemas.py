"""RBAC 管理 API 的 DTO 契约。

Permission 目录是代码拥有的契约，因此权限相关 API 只读；角色创建/更新与
两类授权（用户-角色、角色-权限）是本模块的可变面。
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RoleStatusDTO(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class DataScopeTypeDTO(StrEnum):
    """仅作为存储配置回显；本阶段无任何查询强制语义。"""

    ALL = "all"
    DEPARTMENT = "department"
    DEPARTMENT_AND_CHILDREN = "department_and_children"
    SELF = "self"
    CUSTOM = "custom"


class RoleCreate(BaseModel):
    """创建角色：code 是生命周期稳定标识，创建后不可修改。"""

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9](?:[a-z0-9_-]*)$")
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    data_scope_type: DataScopeTypeDTO = DataScopeTypeDTO.SELF
    sort: int = Field(default=0, ge=0)


class RoleUpdate(BaseModel):
    """更新角色：仅允许展示与配置字段；code/is_system 永不可改。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    data_scope_type: DataScopeTypeDTO | None = None
    sort: int | None = Field(default=None, ge=0)


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None
    data_scope_type: DataScopeTypeDTO
    sort: int
    status: RoleStatusDTO
    is_system: bool
    created_at: datetime
    updated_at: datetime


class RoleDetailRead(RoleRead):
    """角色详情：附当前生效的显式权限码集合（super_admin 恒为空集，动态展开）。"""

    permission_codes: list[str] = Field(default_factory=list)


class RoleListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    keyword: str | None = Field(default=None, max_length=128)


class RolePermissionsRead(BaseModel):
    role_id: UUID
    permission_codes: list[str]


class RolePermissionsUpdate(BaseModel):
    """整体替换角色权限集：服务端计算增/删/不变并在一个事务内完成。"""

    permission_codes: list[str] = Field(min_length=0, max_length=500)


class RolePermissionsReplaceReport(BaseModel):
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)


class PermissionKindDTO(StrEnum):
    ACTION = "action"
    WORKSPACE = "workspace"
    MENU = "menu"


class PermissionStatusDTO(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class PermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    kind: PermissionKindDTO
    module: str
    description: str | None
    status: PermissionStatusDTO
    created_at: datetime
    updated_at: datetime


class PermissionListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    module: str | None = Field(default=None, max_length=64)
    kind: PermissionKindDTO | None = None
    status: PermissionStatusDTO | None = None
    keyword: str | None = Field(default=None, max_length=128)


class UserRoleGrantRead(BaseModel):
    """用户-角色授予记录：assigned_by 是操作者证据，不是授权输入。"""

    model_config = ConfigDict(from_attributes=True)

    role_id: UUID
    role_code: str
    role_name: str
    role_status: RoleStatusDTO
    assigned_by: UUID | None
    assigned_at: datetime


class RoleAssignmentResult(BaseModel):
    """幂等授予结果：newly_assigned=False 表示授予已存在。"""

    user_id: UUID
    role_id: UUID
    newly_assigned: bool


class RoleRemovalResult(BaseModel):
    user_id: UUID
    role_id: UUID
    removed: bool
