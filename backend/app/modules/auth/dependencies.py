"""Reusable FastAPI authentication dependencies.

``get_current_user`` is the single authentication gate for every protected
route. Phase 2 permission dependencies (``require_permission`` and friends)
must build on top of it rather than re-implementing token validation.
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.redis import get_redis_client
from app.db.session import get_db_session, get_session_factory
from app.modules.auth.redis_store import AuthStateStore, RedisAuthStateStore
from app.modules.auth.service import AuthenticatedUser, AuthService, LoginLogWriter

_bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


def get_auth_state_store() -> AuthStateStore:
    """Provide the Redis-backed auth state store; tests override this."""

    return RedisAuthStateStore(get_redis_client())


def get_login_log_writer() -> LoginLogWriter:
    """Provide the independent-session login evidence writer."""

    return LoginLogWriter(get_session_factory())


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    state_store: Annotated[AuthStateStore, Depends(get_auth_state_store)],
    login_log_writer: Annotated[LoginLogWriter, Depends(get_login_log_writer)],
) -> AuthService:
    """Compose the request-scoped authentication service."""

    return AuthService(
        session,
        settings=settings,
        state_store=state_store,
        login_log_writer=login_log_writer,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    service: AuthServiceDep,
) -> AuthenticatedUser:
    """Authenticate the request through a Bearer access token."""

    if credentials is None or not credentials.credentials:
        raise AuthenticationError()
    return await service.get_current_user(credentials.credentials)


CurrentUserDep = Annotated[AuthenticatedUser, Depends(get_current_user)]


async def validate_browser_origin(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Reject cross-site browser origins on cookie-authenticated endpoints.

    Together with ``SameSite`` cookies this is the CSRF strategy for refresh
    and logout: browsers always attach ``Origin`` to cross-site POSTs, so a
    mismatched origin fails closed. Non-browser clients may omit the header.
    """

    origin = request.headers.get("origin")
    if origin is None:
        return
    if origin not in settings.cors_origins:
        raise AuthorizationError("Request origin is not allowed.")
