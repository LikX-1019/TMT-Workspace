"""Canonical API response envelope types."""

from collections.abc import Mapping

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    success: bool = False
    error: ErrorDetail


class SuccessEnvelope[T](BaseModel):
    success: bool = True
    data: T | None = None
    meta: dict[str, object] | None = None


def success_response[T](
    data: T | None = None,
    *,
    meta: Mapping[str, object] | None = None,
) -> SuccessEnvelope[T]:
    """Build a success payload without allowing callers to invent a second shape."""

    return SuccessEnvelope[T](data=data, meta=dict(meta or {}))
