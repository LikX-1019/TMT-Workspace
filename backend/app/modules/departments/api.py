"""Department Management API（Phase 2C）。

move 的环检测（parent=self、移动到后代）完全复用 Phase 1A
``DepartmentService``，路由层不重复实现任何业务规则。
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PageMeta
from app.common.responses import SuccessEnvelope, success_response
from app.db.session import get_db_session
from app.modules.departments.schemas import (
    DepartmentCreate,
    DepartmentRead,
    DepartmentTreeNode,
    DepartmentUpdate,
)
from app.modules.departments.service import DepartmentService
from app.modules.rbac.catalog import Permissions
from app.modules.rbac.dependencies import require_permission

router = APIRouter(prefix="/departments", tags=["Departments"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class DepartmentListQuery(BaseModel):
    """部门列表查询参数。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    keyword: str | None = Field(default=None, max_length=128)
    parent_id: UUID | None = None


class DepartmentMoveRequest(BaseModel):
    """移动部门：new_parent_id 为空表示移动为根节点。"""

    new_parent_id: UUID | None = None


@router.get(
    "",
    response_model=SuccessEnvelope[list[DepartmentRead]],
    summary="分页查询部门列表",
)
async def list_departments(
    _permission: Annotated[object, Depends(require_permission(Permissions.DEPARTMENT_LIST))],
    query: Annotated[DepartmentListQuery, Query()],
    session: DbSession,
) -> SuccessEnvelope[list[DepartmentRead]]:
    items, total = await DepartmentService(session).list_page(
        offset=(query.page - 1) * query.page_size,
        limit=query.page_size,
        keyword=query.keyword,
        parent_id=query.parent_id,
    )
    return success_response(
        [DepartmentRead.model_validate(item) for item in items],
        meta=PageMeta.build(page=query.page, page_size=query.page_size, total=total).model_dump(),
    )


@router.get(
    "/tree",
    response_model=SuccessEnvelope[list[DepartmentTreeNode]],
    summary="查询部门树",
)
async def department_tree(
    _permission: Annotated[object, Depends(require_permission(Permissions.DEPARTMENT_LIST))],
    session: DbSession,
) -> SuccessEnvelope[list[DepartmentTreeNode]]:
    roots = await DepartmentService(session).tree()
    return success_response(roots)


@router.get(
    "/{department_id}",
    response_model=SuccessEnvelope[DepartmentRead],
    summary="查看部门详情",
)
async def get_department(
    _permission: Annotated[object, Depends(require_permission(Permissions.DEPARTMENT_VIEW))],
    department_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[DepartmentRead]:
    department = await DepartmentService(session).get_active(department_id)
    return success_response(DepartmentRead.model_validate(department))


@router.post(
    "",
    response_model=SuccessEnvelope[DepartmentRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建部门",
)
async def create_department(
    _permission: Annotated[object, Depends(require_permission(Permissions.DEPARTMENT_CREATE))],
    payload: DepartmentCreate,
    session: DbSession,
) -> SuccessEnvelope[DepartmentRead]:
    department = await DepartmentService(session).create(payload)
    return success_response(DepartmentRead.model_validate(department))


@router.patch(
    "/{department_id}",
    response_model=SuccessEnvelope[DepartmentRead],
    summary="更新部门信息",
)
async def update_department(
    _permission: Annotated[object, Depends(require_permission(Permissions.DEPARTMENT_UPDATE))],
    department_id: UUID,
    payload: DepartmentUpdate,
    session: DbSession,
) -> SuccessEnvelope[DepartmentRead]:
    department = await DepartmentService(session).update(department_id, payload)
    return success_response(DepartmentRead.model_validate(department))


@router.post(
    "/{department_id}/move",
    response_model=SuccessEnvelope[DepartmentRead],
    summary="调整部门层级归属",
)
async def move_department(
    _permission: Annotated[object, Depends(require_permission(Permissions.DEPARTMENT_MOVE))],
    department_id: UUID,
    payload: DepartmentMoveRequest,
    session: DbSession,
) -> SuccessEnvelope[DepartmentRead]:
    department = await DepartmentService(session).move(department_id, payload.new_parent_id)
    return success_response(DepartmentRead.model_validate(department))


@router.post(
    "/{department_id}/disable",
    response_model=SuccessEnvelope[DepartmentRead],
    summary="禁用部门",
)
async def disable_department(
    _permission: Annotated[object, Depends(require_permission(Permissions.DEPARTMENT_DISABLE))],
    department_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[DepartmentRead]:
    department = await DepartmentService(session).disable(department_id)
    return success_response(DepartmentRead.model_validate(department))


@router.post(
    "/{department_id}/enable",
    response_model=SuccessEnvelope[DepartmentRead],
    summary="恢复部门",
)
async def enable_department(
    _permission: Annotated[object, Depends(require_permission(Permissions.DEPARTMENT_DISABLE))],
    department_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[DepartmentRead]:
    department = await DepartmentService(session).enable(department_id)
    return success_response(DepartmentRead.model_validate(department))
