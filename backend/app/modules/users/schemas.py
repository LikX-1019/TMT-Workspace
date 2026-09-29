"""User and organization assignment DTO contracts."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class EmploymentStatusDTO(StrEnum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    RESIGNED = "resigned"


class AccountStatusDTO(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"


class UserBase(BaseModel):
    employee_no: str = Field(min_length=1, max_length=32)
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9](?:[a-z0-9._-]*)$")
    name: str = Field(min_length=1, max_length=128)
    email: EmailStr | None = None
    mobile: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = Field(default=None, max_length=512)
    employment_status: EmploymentStatusDTO = EmploymentStatusDTO.ACTIVE
    account_status: AccountStatusDTO = AccountStatusDTO.ACTIVE
    primary_supervisor_id: UUID | None = None


class UserCreate(UserBase):
    """Create payload for an employee identity, not an authentication credential."""


class UserUpdate(BaseModel):
    employee_no: str | None = Field(default=None, min_length=1, max_length=32)
    username: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9](?:[a-z0-9._-]*)$",
    )
    name: str | None = Field(default=None, min_length=1, max_length=128)
    email: EmailStr | None = None
    mobile: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = Field(default=None, max_length=512)
    employment_status: EmploymentStatusDTO | None = None
    account_status: AccountStatusDTO | None = None
    primary_supervisor_id: UUID | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_no: str
    username: str
    name: str
    email: str | None
    mobile: str | None
    avatar_url: str | None
    employment_status: EmploymentStatusDTO
    account_status: AccountStatusDTO
    primary_supervisor_id: UUID | None
    last_login_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserDepartmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    department_id: UUID
    is_primary: bool
    created_at: datetime
    updated_at: datetime


class UserPositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    position_id: UUID
    is_primary: bool
    created_at: datetime
    updated_at: datetime
