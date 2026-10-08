"""Authentication DTO contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.users.schemas import AccountStatusDTO, EmploymentStatusDTO


class LoginRequest(BaseModel):
    """Local login payload. The response never carries the refresh token."""

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """Access-token payload returned by login and refresh."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LogoutResponse(BaseModel):
    status: str = "ok"


class PrimaryAssignment(BaseModel):
    """Display reference to the current primary department/position."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class CurrentUserResponse(BaseModel):
    """Authenticated identity profile with resolved authorization state.

    ``roles`` are stable role codes and ``permissions`` are effective
    permission codes (sorted for stable output). Workspaces, menus, and data
    scope are later-phase contracts and stay out of this payload.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employee_no: str
    username: str
    name: str
    email: str | None
    mobile: str | None
    employment_status: EmploymentStatusDTO
    account_status: AccountStatusDTO
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    primary_department: PrimaryAssignment | None = None
    primary_position: PrimaryAssignment | None = None
    last_login_at: datetime | None = None
