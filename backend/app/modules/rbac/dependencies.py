"""可复用的授权依赖：把代码目录中的权限码变成 FastAPI 访问控制。

设计边界（与 Authentication 严格分离）：

- ``get_current_user``（auth 模块）只回答"你是谁？"，负责 401 语义；
  本模块不重复、不捕获、不改写认证错误。
- ``require_permission(...)`` 只回答"你能不能执行这个动作？"，判定完全
  委托 ``AuthorizationService`` 的有效权限解析结果；依赖自身不编码任何
  角色规则、super_admin 特例或状态过滤（disabled/deleted 的排除逻辑全部
  是解析器的职责）。
- 授权读操作只读：不 commit、不修改任何数据库状态。
- 不做跨请求缓存：每个请求直接读 PostgreSQL；权限变更下一请求立即生效。
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.db.session import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.service import AuthenticatedUser
from app.modules.rbac.catalog import CATALOG_PERMISSION_CODES
from app.modules.rbac.service import AuthorizationService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """单个请求内解析一次的授权上下文。

    ``role_codes`` 与 ``permission_codes`` 来自 ``AuthorizationService`` 的
    最终有效结果（union 语义、已排除 disabled/deleted 角色/权限）。它只是
    request-scoped 的解析复用——同一请求内多个权限检查共享一次数据库查询，
    绝不是跨请求缓存。
    """

    user_id: UUID
    role_codes: tuple[str, ...]
    permission_codes: frozenset[str]

    def has_permission(self, permission_code: str) -> bool:
        """判断当前上下文是否持有某个有效权限码。"""

        return permission_code in self.permission_codes


async def get_authorization_context(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthorizationContext:
    """解析当前认证用户的有效角色与权限集合。

    通过 FastAPI 的 Depends 缓存，同一请求内无论多少个 ``require_permission``
    引用它，都只执行一次解析查询。未认证请求在 ``get_current_user`` 处即以
    401 失败，永远不会进入本函数。
    """

    service = AuthorizationService(session)
    user_id = current_user.user.id
    return AuthorizationContext(
        user_id=user_id,
        role_codes=tuple(await service.get_role_codes(user_id)),
        permission_codes=frozenset(await service.get_effective_permission_codes(user_id)),
    )


def require_permission(
    permission_code: str,
) -> Callable[..., Awaitable[AuthorizationContext]]:
    """构造一个要求指定权限码的 FastAPI 依赖（授权入口，唯一强制方式）。

    构造即校验（fail fast）：``permission_code`` 不在代码目录
    ``CATALOG_PERMISSION_CODES`` 中时立即抛 ``ValueError``——这是编程错误
    （例如拼错 ``system:usr:lsit``），必须在路由导入/应用构建阶段暴露，
    而不是让所有请求上线后默默 403。

    用法（与项目 typing 风格一致，优先 FastAPI 原生依赖注入，不用装饰器
    魔法）::

        @router.get(
            "/admin/users",
            dependencies=[Depends(require_permission(Permissions.USER_LIST))],
        )

    或需要读取上下文时::

        context: AuthorizationContext = Depends(require_permission(Permissions.USER_LIST))

    拒绝时抛 ``AuthorizationError``（HTTP 403 / ``AUTHORIZATION_FAILED``）；
    错误响应不回显 ``required_permission``，避免向客户端泄露授权结构。
    """

    if permission_code not in CATALOG_PERMISSION_CODES:
        raise ValueError(
            f"Unknown permission code: {permission_code!r}. "
            "Declare it in app/modules/rbac/catalog.py (and add a Permissions constant) first."
        )

    async def _require_permission(
        context: Annotated[AuthorizationContext, Depends(get_authorization_context)],
        request: Request,
    ) -> AuthorizationContext:
        if not context.has_permission(permission_code):
            # 拒绝证据只进日志（user_id + 权限码 + 路由）；不写 token、不进响应体。
            logger.warning(
                "授权拒绝: user_id=%s permission=%s route=%s %s",
                context.user_id,
                permission_code,
                request.method,
                request.url.path,
            )
            raise AuthorizationError()
        return context

    return _require_permission
