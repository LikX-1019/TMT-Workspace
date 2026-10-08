"""User Management API（Phase 2C）。

边界约定：

- 每个 endpoint 均通过 ``require_permission`` 声明目录权限码；
- PATCH/lifecycle 的自我锁定保护在 service 层强制（operator_id 显式传入）；
- 创建的是员工身份（Employee Identity），绝不接收任何凭据字段；
- ``GET /users`` 的 department 过滤只是查询条件，不是数据范围强制。
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PageMeta
from app.common.responses import SuccessEnvelope, success_response
from app.db.session import get_db_session
from app.modules.auth.dependencies import CurrentUserDep
from app.modules.rbac.catalog import Permissions
from app.modules.rbac.dependencies import require_permission
from app.modules.rbac.schemas import (
    RoleAssignmentResult,
    RoleRemovalResult,
    UserRoleGrantRead,
)
from app.modules.rbac.service import AuthorizationService
from app.modules.users.schemas import (
    UserCreate,
    UserListQuery,
    UserManagementRead,
    UserRead,
    UserUpdate,
)
from app.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["Users"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get(
    "",
    response_model=SuccessEnvelope[list[UserManagementRead]],
    summary="分页查询用户列表",
)
async def list_users(
    _permission: Annotated[object, Depends(require_permission(Permissions.USER_LIST))],
    query: Annotated[UserListQuery, Query()],
    session: DbSession,
) -> SuccessEnvelope[list[UserManagementRead]]:
    service = UserService(session)
    items, total = await service.list_users(query)
    return success_response(
        items,
        meta=PageMeta.build(page=query.page, page_size=query.page_size, total=total).model_dump(),
    )


@router.get(
    "/{user_id}",
    response_model=SuccessEnvelope[UserManagementRead],
    summary="查看用户详情",
)
async def get_user(
    _permission: Annotated[object, Depends(require_permission(Permissions.USER_VIEW))],
    user_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[UserManagementRead]:
    return success_response(await UserService(session).get_management_view(user_id))


@router.post(
    "",
    response_model=SuccessEnvelope[UserRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建员工身份",
    responses={409: {"description": "employee_no/username/email/mobile 冲突"}},
)
async def create_user(
    _permission: Annotated[object, Depends(require_permission(Permissions.USER_CREATE))],
    payload: UserCreate,
    session: DbSession,
) -> SuccessEnvelope[UserRead]:
    # 创建的是员工身份，不是凭据：payload 无 password 字段（schema 层保证）。
    user = await UserService(session).create(payload)
    return success_response(UserRead.model_validate(user))


@router.patch(
    "/{user_id}",
    response_model=SuccessEnvelope[UserRead],
    summary="更新用户（allowlist 字段）",
)
async def update_user(
    _permission: Annotated[object, Depends(require_permission(Permissions.USER_UPDATE))],
    user_id: UUID,
    payload: UserUpdate,
    current_user: CurrentUserDep,
    session: DbSession,
) -> SuccessEnvelope[UserRead]:
    service = UserService(session)
    user = await service.update(user_id, payload, operator_id=current_user.user.id)
    return success_response(UserRead.model_validate(user))


@router.post(
    "/{user_id}/disable",
    response_model=SuccessEnvelope[UserRead],
    summary="禁用用户账号",
)
async def disable_user(
    _permission: Annotated[object, Depends(require_permission(Permissions.USER_DISABLE))],
    user_id: UUID,
    current_user: CurrentUserDep,
    session: DbSession,
) -> SuccessEnvelope[UserRead]:
    user = await UserService(session).disable(user_id, operator_id=current_user.user.id)
    return success_response(UserRead.model_validate(user))


@router.post(
    "/{user_id}/enable",
    response_model=SuccessEnvelope[UserRead],
    summary="恢复用户账号",
)
async def enable_user(
    _permission: Annotated[object, Depends(require_permission(Permissions.USER_DISABLE))],
    user_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[UserRead]:
    user = await UserService(session).enable(user_id)
    return success_response(UserRead.model_validate(user))


@router.post(
    "/{user_id}/resign",
    response_model=SuccessEnvelope[UserRead],
    summary="办理员工离职",
)
async def resign_user(
    _permission: Annotated[object, Depends(require_permission(Permissions.USER_UPDATE))],
    user_id: UUID,
    current_user: CurrentUserDep,
    session: DbSession,
) -> SuccessEnvelope[UserRead]:
    user = await UserService(session).resign(user_id, operator_id=current_user.user.id)
    return success_response(UserRead.model_validate(user))


@router.get(
    "/{user_id}/roles",
    response_model=SuccessEnvelope[list[UserRoleGrantRead]],
    summary="查看用户的角色授予记录",
)
async def list_user_roles(
    _permission: Annotated[object, Depends(require_permission(Permissions.ROLE_VIEW))],
    user_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[list[UserRoleGrantRead]]:
    await UserService(session).get_active(user_id)
    grants = await AuthorizationService(session).list_user_grants(user_id)
    items = [
        UserRoleGrantRead(
            role_id=role.id,
            role_code=role.code,
            role_name=role.name,
            role_status=role.status.value,
            assigned_by=grant.assigned_by,
            assigned_at=grant.assigned_at,
        )
        for grant, role in grants
    ]
    return success_response(items)


@router.post(
    "/{user_id}/roles/{role_id}",
    response_model=SuccessEnvelope[RoleAssignmentResult],
    summary="为用户授予角色（幂等）",
)
async def assign_role(
    _permission: Annotated[object, Depends(require_permission(Permissions.ROLE_ASSIGN))],
    user_id: UUID,
    role_id: UUID,
    current_user: CurrentUserDep,
    session: DbSession,
) -> SuccessEnvelope[RoleAssignmentResult]:
    # 目标用户必须存在；assigned_by 恒为当前认证操作者，禁止客户端提交。
    await UserService(session).get_active(user_id)
    resolved_role_id, newly_assigned = await AuthorizationService(session).assign_role_by_id(
        user_id, role_id, assigned_by=current_user.user.id
    )
    # TODO(audit): role assignment 属于未来审计系统的 sensitive event。
    return success_response(
        RoleAssignmentResult(
            user_id=user_id, role_id=resolved_role_id, newly_assigned=newly_assigned
        )
    )


@router.delete(
    "/{user_id}/roles/{role_id}",
    response_model=SuccessEnvelope[RoleRemovalResult],
    summary="移除用户的角色",
)
async def remove_role(
    _permission: Annotated[object, Depends(require_permission(Permissions.ROLE_ASSIGN))],
    user_id: UUID,
    role_id: UUID,
    session: DbSession,
) -> SuccessEnvelope[RoleRemovalResult]:
    await UserService(session).get_active(user_id)
    removed = await AuthorizationService(session).remove_role_by_id(user_id, role_id)
    return success_response(RoleRemovalResult(user_id=user_id, role_id=role_id, removed=removed))
