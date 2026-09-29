"""Position DTO contracts."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PositionStatusDTO(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class PositionBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9](?:[a-z0-9._-]*)$")
    description: str | None = Field(default=None, max_length=512)
    sort: int = Field(default=0, ge=0)
    status: PositionStatusDTO = PositionStatusDTO.ACTIVE


class PositionCreate(PositionBase):
    """Create payload for an organizational job."""


class PositionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9](?:[a-z0-9._-]*)$",
    )
    description: str | None = Field(default=None, max_length=512)
    sort: int | None = Field(default=None, ge=0)
    status: PositionStatusDTO | None = None


class PositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    description: str | None
    sort: int
    status: PositionStatusDTO
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
