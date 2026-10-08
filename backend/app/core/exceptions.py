"""Application exception hierarchy and stable error codes."""

from collections.abc import Mapping
from typing import Any


class AppError(Exception):
    """Base class for expected application errors.

    API handlers translate this into a consistent response envelope. Unexpected
    exceptions must never be converted into this class just to hide their cause.
    """

    code = "APP_ERROR"
    status_code = 500
    message = "An unexpected application error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = dict(details or {})


class AuthenticationError(AppError):
    code = "AUTHENTICATION_FAILED"
    status_code = 401
    message = "Authentication is required."


class SessionRevokedError(AppError):
    """The session referenced by valid credentials was revoked server-side."""

    code = "SESSION_REVOKED"
    status_code = 401
    message = "The session is no longer active. Please sign in again."


class RateLimitError(AppError):
    """Too many attempts within the configured window."""

    code = "RATE_LIMITED"
    status_code = 429
    message = "Too many attempts. Please try again later."


class PasswordPolicyError(AppError):
    """A proposed password violates the configured password policy."""

    code = "PASSWORD_POLICY_VIOLATED"
    status_code = 422
    message = "The password does not satisfy the password policy."


class AuthorizationError(AppError):
    code = "AUTHORIZATION_FAILED"
    status_code = 403
    message = "You do not have permission to perform this action."


class NotFoundError(AppError):
    code = "RESOURCE_NOT_FOUND"
    status_code = 404
    message = "Resource not found."


class ConflictError(AppError):
    code = "RESOURCE_CONFLICT"
    status_code = 409
    message = "The request conflicts with existing state."


class ValidationError(AppError):
    code = "REQUEST_VALIDATION_FAILED"
    status_code = 422
    message = "The request could not be processed."
