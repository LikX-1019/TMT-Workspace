"""Position Management API（Phase 2C）。

Position 是组织岗位，不是授权角色：任何 Position 端点都不产生
Role/Permission 副作用（PositionService 中不含任何 RBAC 引用）。
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PageMeta
from app.common.responses import SuccessEnvelope, success_response
from app.db.session import get_db_session
from app.modules.positions.schemas import (
    PositionCreate,
    PositionRead,
    PositionUpdate,
)
from app.modules.positions.service import PositionService
from app.modules.rbac.catalog import Permissions
from app.modules.rbac.dependencies import require_permission

router = APIRouter(prefix="/positions", tags=["Positions"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class PositionListQuery(BaseModel):
    """职位列表查询参数。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    keyword: str | None = Field(default=None, max_length=128)


@router.get(
    "",
    response_model=SuccessEnvelope[list[PositionRead]],
    summary="分页查询职位列表",
)
async def list_positions(
    _permission: Annotated[object, Depends(require_permission(Permissions.POSITION_LIST))],
    query: Annotated[PositionListQuery, Query()],
    session: DbSession,
) -> SuccessEnvelope[list[PositionRead]]:
    items, total = await PositionService(session).list_page(
        offset=(query.page - 1) * query.page_size,
        limit=query.page_size,
        keyword=query.keyword,
    )
    return success_response(
        [PositionRead.model_validate(item) for item in items],
        meta=PageMeta.build(page=query.page, page_size=query.page_size, total=total).model_dump(),
    )


@router.get(
    "/{position_id}",
    response_model=SuccessEnvelope[PositionRead],
    summary="查看职位详情",
)
async def get_position(
    _permission: Annotated[object, Depends(require_permission(Permissions.POSITION_VIEW))],
    position_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[PositionRead]:
    position = await PositionService(session).get_active(position_id)
    return success_response(PositionRead.model_validate(position))


@router.post(
    "",
    response_model=SuccessEnvelope[PositionRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建职位",
)
async def create_position(
    _permission: Annotated[object, Depends(require_permission(Permissions.POSITION_CREATE))],
    payload: PositionCreate,
    session: DbSession,
) -> SuccessEnvelope[PositionRead]:
    position = await PositionService(session).create(payload)
    return success_response(PositionRead.model_validate(position))


@router.patch(
    "/{position_id}",
    response_model=SuccessEnvelope[PositionRead],
    summary="更新职位信息",
)
async def update_position(
    _permission: Annotated[object, Depends(require_permission(Permissions.POSITION_UPDATE))],
    position_id: UUID,
    payload: PositionUpdate,
    session: DbSession,
) -> SuccessEnvelope[PositionRead]:
    position = await PositionService(session).update(position_id, payload)
    return success_response(PositionRead.model_validate(position))


@router.post(
    "/{position_id}/disable",
    response_model=SuccessEnvelope[PositionRead],
    summary="禁用职位",
)
async def disable_position(
    _permission: Annotated[object, Depends(require_permission(Permissions.POSITION_DISABLE))],
    position_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[PositionRead]:
    position = await PositionService(session).disable(position_id)
    return success_response(PositionRead.model_validate(position))


@router.post(
    "/{position_id}/enable",
    response_model=SuccessEnvelope[PositionRead],
    summary="恢复职位",
)
async def enable_position(
    _permission: Annotated[object, Depends(require_permission(Permissions.POSITION_DISABLE))],
    position_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[PositionRead]:
    position = await PositionService(session).enable(position_id)
    return success_response(PositionRead.model_validate(position))
