"""Health API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import SuccessEnvelope, success_response
from app.core.config import Settings, get_settings
from app.db.session import get_db_session

router = APIRouter(tags=["health"])


@router.get("/health", response_model=SuccessEnvelope[dict[str, str]])
async def get_health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SuccessEnvelope[dict[str, str]]:
    """Return liveness and basic process metadata."""

    return success_response(
        {
            "status": "ok",
            "environment": settings.environment,
            "version": "0.1.0",
        }
    )


@router.get("/health/ready", response_model=SuccessEnvelope[dict[str, str]])
async def get_readiness(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SuccessEnvelope[dict[str, str]]:
    """Verify that the application can execute a database query."""

    await session.execute(text("SELECT 1"))
    return success_response({"status": "ready", "database": "ok"})
