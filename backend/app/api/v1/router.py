"""组合全部暴露在 /api/v1 下的模块路由。"""

from fastapi import APIRouter

from app.modules.auth.api import router as auth_router
from app.modules.departments.api import router as departments_router
from app.modules.health.api import router as health_router
from app.modules.positions.api import router as positions_router
from app.modules.rbac.api import router as rbac_router
from app.modules.users.api import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(health_router)
api_router.include_router(users_router)
api_router.include_router(departments_router)
api_router.include_router(positions_router)
api_router.include_router(rbac_router)
