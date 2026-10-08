"""Role / Permission Management API（Phase 2C）。

权限目录是代码拥有的契约：Permission API 只读，权限定义只能通过
``catalog.py`` + ``sync-permissions`` 变更。角色权限配置采用整体替换
语义（``PUT /roles/{id}/permissions``），服务端在一个事务内计算
增/删/不变；``super_admin`` 的能力来自动态展开，拒绝显式授权。
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PageMeta
from app.common.responses import SuccessEnvelope, success_response
from app.db.session import get_db_session
from app.modules.rbac.catalog import Permissions
from app.modules.rbac.dependencies import require_permission
from app.modules.rbac.models import DataScopeType, PermissionKind, PermissionStatus
from app.modules.rbac.schemas import (
    PermissionListQuery,
    PermissionRead,
    RoleCreate,
    RoleDetailRead,
    RoleListQuery,
    RolePermissionsRead,
    RolePermissionsReplaceReport,
    RolePermissionsUpdate,
    RoleRead,
    RoleUpdate,
)
from app.modules.rbac.service import (
    PermissionCatalogService,
    RoleCreateRequest,
    RoleService,
)

router = APIRouter(tags=["Roles", "Permissions"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


# ---------------------------------------------------------------- Roles


@router.get(
    "/roles",
    response_model=SuccessEnvelope[list[RoleRead]],
    summary="分页查询角色列表",
)
async def list_roles(
    _permission: Annotated[object, Depends(require_permission(Permissions.ROLE_LIST))],
    query: Annotated[RoleListQuery, Query()],
    session: DbSession,
) -> SuccessEnvelope[list[RoleRead]]:
    items, total = await RoleService(session).list_page(
        offset=(query.page - 1) * query.page_size,
        limit=query.page_size,
        keyword=query.keyword,
    )
    return success_response(
        [RoleRead.model_validate(item) for item in items],
        meta=PageMeta.build(page=query.page, page_size=query.page_size, total=total).model_dump(),
    )


@router.get(
    "/roles/{role_id}",
    response_model=SuccessEnvelope[RoleDetailRead],
    summary="查看角色详情（含显式权限码）",
)
async def get_role(
    _permission: Annotated[object, Depends(require_permission(Permissions.ROLE_VIEW))],
    role_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[RoleDetailRead]:
    service = RoleService(session)
    role = await service.get_active_by_id(role_id)
    detail = RoleDetailRead.model_validate(role)
    detail.permission_codes = sorted(await service.get_explicit_permission_codes(role_id))
    return success_response(detail)


@router.post(
    "/roles",
    response_model=SuccessEnvelope[RoleRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建角色",
)
async def create_role(
    _permission: Annotated[object, Depends(require_permission(Permissions.ROLE_CREATE))],
    payload: RoleCreate,
    session: DbSession,
) -> SuccessEnvelope[RoleRead]:
    # API 层不接收 is_system：系统角色只能由 catalog sync 创建。
    role = await RoleService(session).create_role(
        RoleCreateRequest(
            code=payload.code,
            name=payload.name,
            description=payload.description,
            data_scope_type=DataScopeType(payload.data_scope_type.value),
            sort=payload.sort,
            is_system=False,
        )
    )
    return success_response(RoleRead.model_validate(role))


@router.patch(
    "/roles/{role_id}",
    response_model=SuccessEnvelope[RoleRead],
    summary="更新角色（code/is_system 不可改）",
)
async def update_role(
    _permission: Annotated[object, Depends(require_permission(Permissions.ROLE_UPDATE))],
    role_id: UUID,
    payload: RoleUpdate,
    session: DbSession,
) -> SuccessEnvelope[RoleRead]:
    role = await RoleService(session).update_profile(
        role_id,
        name=payload.name,
        description=payload.description,
        sort=payload.sort,
        data_scope_type=(
            DataScopeType(payload.data_scope_type.value) if payload.data_scope_type else None
        ),
    )
    return success_response(RoleRead.model_validate(role))


@router.post(
    "/roles/{role_id}/disable",
    response_model=SuccessEnvelope[RoleRead],
    summary="禁用角色",
)
async def disable_role(
    _permission: Annotated[object, Depends(require_permission(Permissions.ROLE_DISABLE))],
    role_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[RoleRead]:
    role = await RoleService(session).disable_role(role_id)
    return success_response(RoleRead.model_validate(role))


@router.post(
    "/roles/{role_id}/enable",
    response_model=SuccessEnvelope[RoleRead],
    summary="恢复角色",
)
async def enable_role(
    _permission: Annotated[object, Depends(require_permission(Permissions.ROLE_DISABLE))],
    role_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[RoleRead]:
    role = await RoleService(session).enable_role(role_id)
    return success_response(RoleRead.model_validate(role))


# ------------------------------------------------- Role-Permission 配置


@router.get(
    "/roles/{role_id}/permissions",
    response_model=SuccessEnvelope[RolePermissionsRead],
    summary="查看角色的显式权限码集合",
)
async def list_role_permissions(
    _permission: Annotated[object, Depends(require_permission(Permissions.ROLE_VIEW))],
    role_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[RolePermissionsRead]:
    service = RoleService(session)
    role = await service.get_active_by_id(role_id)
    codes = await service.get_explicit_permission_codes(role.id)
    return success_response(RolePermissionsRead(role_id=role.id, permission_codes=sorted(codes)))


@router.put(
    "/roles/{role_id}/permissions",
    response_model=SuccessEnvelope[RolePermissionsReplaceReport],
    summary="整体替换角色权限集",
    responses={409: {"description": "super_admin 的权限由系统动态管理，不可编辑"}},
)
async def replace_role_permissions(
    _permission: Annotated[object, Depends(require_permission(Permissions.ROLE_ASSIGN))],
    role_id: UUID,
    payload: RolePermissionsUpdate,
    session: DbSession,
) -> SuccessEnvelope[RolePermissionsReplaceReport]:
    outcome = await RoleService(session).replace_permissions(role_id, payload.permission_codes)
    # TODO(audit): permission assignment 属于未来审计系统的 sensitive event。
    return success_response(
        RolePermissionsReplaceReport(
            added=outcome.added, removed=outcome.removed, unchanged=outcome.unchanged
        )
    )


# ------------------------------------------------------------ Permissions


@router.get(
    "/permissions",
    response_model=SuccessEnvelope[list[PermissionRead]],
    summary="分页查询权限目录（只读）",
)
async def list_permissions(
    _permission: Annotated[object, Depends(require_permission(Permissions.PERMISSION_LIST))],
    query: Annotated[PermissionListQuery, Query()],
    session: DbSession,
) -> SuccessEnvelope[list[PermissionRead]]:
    items, total = await PermissionCatalogService(session).list_permissions(
        offset=(query.page - 1) * query.page_size,
        limit=query.page_size,
        module=query.module,
        kind=PermissionKind(query.kind.value) if query.kind else None,
        status=PermissionStatus(query.status.value) if query.status else None,
        keyword=query.keyword,
    )
    return success_response(
        [PermissionRead.model_validate(item) for item in items],
        meta=PageMeta.build(page=query.page, page_size=query.page_size, total=total).model_dump(),
    )


@router.get(
    "/permissions/{permission_id}",
    response_model=SuccessEnvelope[PermissionRead],
    summary="查看权限定义（只读）",
)
async def get_permission(
    _permission: Annotated[object, Depends(require_permission(Permissions.PERMISSION_LIST))],
    permission_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[PermissionRead]:
    permission = await PermissionCatalogService(session).get_permission(permission_id)
    return success_response(PermissionRead.model_validate(permission))
