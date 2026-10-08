"""Authentication HTTP routes.

Cookie contract: the refresh token travels only in an ``HttpOnly`` cookie
scoped to the auth path; response bodies expose the access token exclusively.
Refresh and logout authenticate through the cookie, so they validate the
browser origin (CSRF strategy: SameSite cookie + origin validation).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.common.responses import SuccessEnvelope, success_response
from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError
from app.core.security import refresh_cookie_max_age_seconds
from app.modules.auth.dependencies import (
    AuthServiceDep,
    CurrentUserDep,
    validate_browser_origin,
)
from app.modules.auth.schemas import (
    CurrentUserResponse,
    LoginRequest,
    LogoutResponse,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    """Attach the host-only refresh cookie; JavaScript never sees the value."""

    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=refresh_cookie_max_age_seconds(settings.refresh_token_ttl_days),
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=settings.refresh_cookie_path,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
    )


def _read_refresh_cookie(request: Request, settings: Settings) -> str:
    token = request.cookies.get(settings.refresh_cookie_name)
    if not token:
        raise AuthenticationError("Refresh token is missing.")
    return token


def _client_ip(request: Request) -> str | None:
    """Direct peer address only; forwarded headers require a proxy contract."""

    if request.client is None:
        return None
    return request.client.host


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


@router.post("/login", response_model=SuccessEnvelope[TokenResponse])
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SuccessEnvelope[TokenResponse]:
    """Authenticate with username/password and open a refresh-cookie session."""

    outcome = await service.login(
        payload,
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    _set_refresh_cookie(response, outcome.refresh_token, settings)
    return success_response(
        TokenResponse(
            access_token=outcome.access_token,
            token_type="bearer",
            expires_in=outcome.expires_in,
        )
    )


@router.post(
    "/refresh",
    response_model=SuccessEnvelope[TokenResponse],
    dependencies=[Depends(validate_browser_origin)],
)
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SuccessEnvelope[TokenResponse]:
    """Rotate the refresh cookie and issue a fresh access token."""

    outcome = await service.refresh(
        _read_refresh_cookie(request, settings),
        client_ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    _set_refresh_cookie(response, outcome.refresh_token, settings)
    return success_response(
        TokenResponse(
            access_token=outcome.access_token,
            token_type="bearer",
            expires_in=outcome.expires_in,
        )
    )


@router.post(
    "/logout",
    response_model=SuccessEnvelope[LogoutResponse],
    dependencies=[Depends(validate_browser_origin)],
)
async def logout(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SuccessEnvelope[LogoutResponse]:
    """Revoke the cookie's session family and clear the cookie, idempotently."""

    await service.logout(request.cookies.get(settings.refresh_cookie_name))
    _clear_refresh_cookie(response, settings)
    return success_response(LogoutResponse())


@router.get("/me", response_model=SuccessEnvelope[CurrentUserResponse])
async def me(
    current_user: CurrentUserDep,
    service: AuthServiceDep,
) -> SuccessEnvelope[CurrentUserResponse]:
    """Return the authenticated identity; extended in Phase 2 with RBAC data."""

    return success_response(await service.build_profile(current_user.user))
