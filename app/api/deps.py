"""API 依赖：认证上下文装配（Phase 4）。

两个入口，用途严格区分
--------------------

```text
get_current_actor                        → 已认证**且**已完成强制改密
                                           （所有受保护业务端点的默认入口）
get_current_actor_allow_password_change  → 已认证，**允许**处于强制改密状态
                                           仅供 /auth/me、/auth/password、/auth/logout
```
为什么要把"强制改密"做成依赖而不是一个标志位
------------------------------------------
`04 §2` 冻结"管理员重置后首次登录必须修改密码"。
如果服务端只把 `must_change_password` 返回给客户端、由前端决定是否弹窗，
那么任何人只要**直接调接口**就能带着"应当改密"的会话使用全部功能 ——
该策略变成装饰品。

因此把判定放进 `get_current_actor`：**所有**受保护端点自动继承该约束，
不需要每个端点各自记得检查（散落检查必然漏掉某一条路径，
这正是本项目在 Phase 2 已经踩过的坑）。
需要"允许改密状态下访问"的极少数端点显式使用宽松入口 ——
依赖关系在**代码里**可见，而不是靠文档约定。

客户端 IP 的来源（刻意保守）
-------------------------
只取 ASGI 的 socket 对端地址（`request.client.host`），
**不读** `X-Forwarded-For`。
原因：在没有"可信代理列表"配置的前提下信任 XFF，
等于让任何客户端都能伪造自己的来源 IP —— 那会让
`04 §3` 要求记录的 IP 变成无意义甚至误导性的数据。
可信代理链路的处理属 Phase 9 hardening 范围（届时会同时冻结受信代理配置）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actor import CurrentActor
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security.token import extract_bearer_token
from app.db.session import get_db
from app.services.auth import AuthService
from app.services.mfa_management import MfaManagementService
from app.services.session import AuthenticatedSession, SessionService
from app.services.session_management import SessionManagementService

_UNAUTHENTICATED_MESSAGE = "认证失败或登录状态已失效"

#: 强制改密期间访问其他受保护端点时的拒绝文案。
#:
#: 用 403（而非 401）是刻意的：调用者**是**已认证的，
#: 只是当前状态下不允许访问该资源；401 会让客户端误以为需要重新登录，
#: 进而清掉会话，用户反而无法完成改密。
_PASSWORD_CHANGE_REQUIRED_MESSAGE = "当前账号被要求先修改密码，请先调用 POST /auth/password"  # noqa: S105


def client_ip(request: Request) -> str | None:
    """返回请求来源 IP（仅 socket 对端，见模块 docstring）。"""
    return request.client.host if request.client is not None else None


def client_user_agent(request: Request) -> str | None:
    """返回 `User-Agent`（缺失时为 None，不编造默认值）。"""
    return request.headers.get("User-Agent")


async def get_bearer_token(request: Request) -> str:
    """解析 `Authorization: Bearer <token>`。

    Raises:
        AuthenticationError: 头缺失 / 方案不匹配 / 令牌形状非法。
            文案统一，不区分原因（避免向未认证者泄漏解析细节）。
    """
    token = extract_bearer_token(request.headers.get("Authorization"))
    if token is None:
        raise AuthenticationError(_UNAUTHENTICATED_MESSAGE)
    return token


async def get_session_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SessionService:
    """提供会话服务。"""
    return SessionService(session)


async def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthService:
    """提供认证服务。"""
    return AuthService(session)


async def get_session_management_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SessionManagementService:
    """提供会话管理服务（列表 / 在线查询 / 踢下线）。

    与 `AuthService` 一致，默认不注入审计记录器：
    审计事件通过端口产生，**落库属 Phase 6**（DD-08 未冻结）。
    """
    return SessionManagementService(session)


async def get_mfa_management_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MfaManagementService:
    """提供 MFA 管理服务（状态 / 绑定 / 启用 / 禁用 / 挑战核销）。

    与 `AuthService` 一致，默认不注入审计记录器：审计事件经端口产生，
    **落库属 Phase 6**（DD-08 未冻结）。
    """
    return MfaManagementService(session)


async def get_authenticated_session(
    request: Request,
    token: Annotated[str, Depends(get_bearer_token)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> AuthenticatedSession:
    """校验令牌并返回认证上下文（会话 + 用户 + 操作者）。

    Raises:
        AuthenticationError: 令牌无效 / 过期 / 已撤销 / 所属用户不可用。
    """
    return await service.authenticate(
        access_token=token,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )


async def get_current_actor(
    authenticated: Annotated[AuthenticatedSession, Depends(get_authenticated_session)],
) -> CurrentActor:
    """当前操作者（**强制已改密**）。

    Raises:
        PermissionDeniedError: 处于强制改密状态。
    """
    if authenticated.user.must_change_password:
        raise PermissionDeniedError(_PASSWORD_CHANGE_REQUIRED_MESSAGE)
    return authenticated.actor


async def get_current_actor_allow_password_change(
    authenticated: Annotated[AuthenticatedSession, Depends(get_authenticated_session)],
) -> CurrentActor:
    """当前操作者（**允许**处于强制改密状态）。

    只供 `/auth/me`、`/auth/password`、`/auth/logout` 使用：
    前两个是"完成强制改密"所必需的（否则用户被永久锁在门外），
    登出则必须始终可用（否则用户无法退出这个状态）。
    """
    return authenticated.actor


#: 便于端点使用 `Annotated` 风格声明的类型别名。
CurrentActorDep = Annotated[CurrentActor, Depends(get_current_actor)]
CurrentActorAllowPasswordChangeDep = Annotated[
    CurrentActor, Depends(get_current_actor_allow_password_change)
]
BearerTokenDep = Annotated[str, Depends(get_bearer_token)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
SessionManagementServiceDep = Annotated[
    SessionManagementService, Depends(get_session_management_service)
]
MfaManagementServiceDep = Annotated[MfaManagementService, Depends(get_mfa_management_service)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]


__all__ = [
    "AuthServiceDep",
    "BearerTokenDep",
    "CurrentActorAllowPasswordChangeDep",
    "CurrentActorDep",
    "DbSessionDep",
    "MfaManagementServiceDep",
    "SessionManagementServiceDep",
    "client_ip",
    "client_user_agent",
    "get_auth_service",
    "get_authenticated_session",
    "get_bearer_token",
    "get_current_actor",
    "get_current_actor_allow_password_change",
    "get_mfa_management_service",
    "get_session_management_service",
    "get_session_service",
]
