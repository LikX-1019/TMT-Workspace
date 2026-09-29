"""Compose all module routers exposed under /api/v1."""

from fastapi import APIRouter

from tmt_workspace.modules.health.api import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
