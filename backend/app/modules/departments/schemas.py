"""Department DTO contracts."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DepartmentStatusDTO(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class DepartmentBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9](?:[a-z0-9._-]*)$")
    parent_id: UUID | None = None
    leader_id: UUID | None = None
    sort: int = Field(default=0, ge=0)
    status: DepartmentStatusDTO = DepartmentStatusDTO.ACTIVE


class DepartmentCreate(DepartmentBase):
    """Create payload for an organization tree node."""


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9](?:[a-z0-9._-]*)$",
    )
    parent_id: UUID | None = None
    leader_id: UUID | None = None
    sort: int | None = Field(default=None, ge=0)
    status: DepartmentStatusDTO | None = None


class DepartmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_id: UUID | None
    name: str
    code: str
    leader_id: UUID | None
    sort: int
    status: DepartmentStatusDTO
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DepartmentTreeNode(DepartmentRead):
    children: list["DepartmentTreeNode"] = Field(default_factory=list)
