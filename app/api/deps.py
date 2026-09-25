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

Phase 8 追加：声明式 API 权限绑定
------------------------------
`require_api_permission(api_code, *, action, resource_type)` 按
**DD-20 §5.1.3 冻结**的方式把"这个端点需要哪个 API 权限"
写在路由装饰器上（依赖声明），而不是靠路径正则匹配。
绑定同时声明拒绝审计的动作 —— 路由级授权发生在服务层之前，
若不在此留痕，"反复尝试调用无权接口"在审计里不可见。
详见该函数自身的 docstring。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction
from app.audit.buffer import BufferingAuditRecorder
from app.auth.actor import CurrentActor
from app.core.context import set_actor_id
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security.token import extract_bearer_token
from app.db.session import get_db
from app.services.audit_guard import AuditGuard
from app.services.auth import AuthService
from app.services.authorization import AuthorizationService
from app.services.department import DepartmentService
from app.services.dict import DictService
from app.services.mfa_management import MfaManagementService
from app.services.permission_contract import PermissionContractService
from app.services.permission_resource import PermissionResourceService
from app.services.role import RoleService
from app.services.role_data_scope import RoleDataScopeService
from app.services.role_permission import RolePermissionService
from app.services.session import AuthenticatedSession, SessionService
from app.services.session_management import SessionManagementService
from app.services.system_param import SystemParameterService, resolve_mfa_required_default
from app.services.user import UserService

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
    """提供会话服务。

    必须注入审计记录器：`SessionService.authenticate` 是**每个受保护端点**
    的必经之路，它在令牌无效、会话已撤销、用户不可用、以及"已轮换的
    Refresh Token 被复用"（DD-02 的 family revocation）时都会写事件。
    默认的 `NullAuditRecorder` 会让这些事件止步于内存 ——
    于是"谁拿着一个失效令牌反复尝试"这件事在审计里完全不可见。
    """
    return SessionService(session, audit=BufferingAuditRecorder())


async def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthService:
    """提供认证服务。

    Phase 6 起注入 `BufferingAuditRecorder`：审计事件被写入**请求级缓冲**，
    由中间件在同一请求结束前用独立事务落库。
    在此之前这里是 `NullAuditRecorder` —— 也就是说 Phase 2~5 产生的审计事件
    全部止步于内存，只有测试断言看得见；这正是 Phase 6 要补的口子。

    Phase 7 起 `system_default` 来自**系统参数表**（§12.1 的既定安排）：
    `resolve_mfa_required_default` 读 `mfa.required_default`，
    行缺失时回退环境变量 `MFA_REQUIRED_DEFAULT`（与迁移前口径一致）。
    在这里（异步的装配点）解析，是因为 `MfaPolicyResolver` 的
    `system_default` 是构造期入参 —— 解析需要 IO，构造是同步的。
    """
    return AuthService(
        session,
        audit=BufferingAuditRecorder(),
        system_default=await resolve_mfa_required_default(session),
    )


async def get_session_management_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SessionManagementService:
    """提供会话管理服务（列表 / 在线查询 / 踢下线）。"""
    return SessionManagementService(session, audit=BufferingAuditRecorder())


async def get_mfa_management_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MfaManagementService:
    """提供 MFA 管理服务（状态 / 绑定 / 启用 / 禁用 / 挑战核销）。

    `system_default` 与 `get_auth_service` 取**同一个来源**：
    `GET /auth/mfa` 报告的"是否要求二次验证"必须与登录时的判定一致，
    否则"这个要求是谁提的"会出现两个答案。
    """
    return MfaManagementService(
        session,
        audit=BufferingAuditRecorder(),
        system_default=await resolve_mfa_required_default(session),
    )


async def get_dict_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DictService:
    """提供字典服务（Phase 7：字典类型 / 字典项）。"""
    return DictService(session, audit=BufferingAuditRecorder())


async def get_system_param_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SystemParameterService:
    """提供系统参数服务（Phase 7：类型化配置）。"""
    return SystemParameterService(session, audit=BufferingAuditRecorder())


async def get_authorization_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthorizationService:
    """提供集中式授权服务（路由级 API 权限绑定的判定入口）。"""
    return AuthorizationService(session)


async def get_user_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserService:
    """提供用户服务（FINDING-8-01：`08 §4` 端点的补交付）。"""
    return UserService(session, audit=BufferingAuditRecorder())


async def get_role_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoleService:
    """提供角色服务（FINDING-8-01：`08 §7` 实体 CRUD 的补交付）。"""
    return RoleService(session, audit=BufferingAuditRecorder())


async def get_department_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> DepartmentService:
    """提供部门服务（FINDING-8-01：`08 §6` 端点的补交付）。"""
    return DepartmentService(session, audit=BufferingAuditRecorder())


async def get_permission_resource_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PermissionResourceService:
    """提供权限资源服务（Phase 8：Page / Menu / Button / API / Field 定义）。"""
    return PermissionResourceService(session, audit=BufferingAuditRecorder())


async def get_role_permission_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RolePermissionService:
    """提供角色授权服务（Phase 8：四类二元授权 + 字段等级）。"""
    return RolePermissionService(session, audit=BufferingAuditRecorder())


async def get_role_data_scope_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RoleDataScopeService:
    """提供角色数据范围服务（Phase 8：DD-07 的 CUSTOM 持久化 + DD-19 求并输入）。"""
    return RoleDataScopeService(session, audit=BufferingAuditRecorder())


async def get_permission_contract_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PermissionContractService:
    """提供前端动态权限契约服务（Phase 8 / Spec `09 §2`）。

    刻意**不**注入审计记录器：该端点返回的是**调用者本人的**权限快照，
    且每次打开后台页面都会调用 —— 逐次记审计会把审计表变成访问日志。
    判定依据与边界见 `endpoints/auth.py::permissions` 与
    `docs/DESIGN-DECISIONS.md` §15（INTERIM-7-05 的同一取向）。
    """
    return PermissionContractService(session)


#: 以 `resource_code` 声明的 API 权限依赖签名。
ApiPermissionDependency = Callable[..., Awaitable[None]]


def require_api_permission(
    api_code: str,
    *,
    action: AuditAction,
    resource_type: str,
) -> ApiPermissionDependency:
    """声明式 API 权限绑定（**DD-20 §5.1.3 冻结**）。

    用法::

        @router.post(
            "/roles/{role_id}/permissions/pages",
            dependencies=[
                Depends(
                    require_api_permission(
                        ApiPermissionCode.ROLE_MANAGE,
                        action=AuditAction.ROLE_PERMISSION_UPDATE,
                        resource_type="ROLE",
                    )
                )
            ],
        )

    为什么是声明式绑定而不是"路径 ↔ 权限"正则匹配
    ------------------------------------------
    DD-20 §5.1.3 的冻结理由：`api_method` + `api_path` 的正则匹配在
    `{id}` 占位、尾斜杠、方法覆盖等场景下容易**漏判**，而漏判即越权。
    声明式绑定在路由注册期就固定下来，漏声明的路由可以被静态扫描出来
    （"未声明授权的路由 = 启动警告"属 Phase 9 hardening）。

    为什么要显式传 `action` / `resource_type`
    ----------------------------------------
    本项目有一条与授权同等重要的义务：**拒绝必须留痕**
    （`10 §8`；Phase 2 由 `denial_audited` 固化）。路由级授权发生在
    服务层**之前**，此时服务层的守卫还没机会执行 —— 若这里不留痕，
    "有人反复尝试调用无权接口"这件事在审计里将完全不可见。

    因此本依赖在拒绝时写一条 FAILURE 审计，动作由调用方声明
    （与服务层保持同一动作名，便于按动作检索一次拿全）。

    Note:
        服务层**同时**保留自己的授权校验（纵深防御）：
        路由级拒绝时只有本依赖写审计，服务层拒绝时只有服务层写审计，
        同一次请求不会产生两条重复的 FAILURE 记录。
    """

    async def _dependency(
        actor: CurrentActorDep,
        session: DbSessionDep,
    ) -> None:
        guard = AuditGuard(BufferingAuditRecorder(), resource_type)
        with guard.denial_audited(actor=actor, action=action, resource_id=None):
            await AuthorizationService(session).assert_api_permission(
                actor=actor, api_code=api_code
            )

    return _dependency


async def get_authenticated_session(
    request: Request,
    token: Annotated[str, Depends(get_bearer_token)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> AuthenticatedSession:
    """校验令牌并返回认证上下文（会话 + 用户 + 操作者）。

    Raises:
        AuthenticationError: 令牌无效 / 过期 / 已撤销 / 所属用户不可用。

    Note:
        认证成功后把操作者写进请求上下文（`set_actor_id`）。
        访问日志（`access_logs.operator_id`）由中间件产生，而中间件**不解析令牌**
        —— 令牌校验只此一处，中间件重复解析会带来第二个真相。
        这个写入能被中间件看见，前提是纯 ASGI 中间件（见 `middleware/trace.py`）。
    """
    authenticated = await service.authenticate(
        access_token=token,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    set_actor_id(authenticated.actor.user_id)
    return authenticated


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
DictServiceDep = Annotated[DictService, Depends(get_dict_service)]
SystemParamServiceDep = Annotated[SystemParameterService, Depends(get_system_param_service)]
PermissionResourceServiceDep = Annotated[
    PermissionResourceService, Depends(get_permission_resource_service)
]
RolePermissionServiceDep = Annotated[RolePermissionService, Depends(get_role_permission_service)]
RoleDataScopeServiceDep = Annotated[RoleDataScopeService, Depends(get_role_data_scope_service)]
PermissionContractServiceDep = Annotated[
    PermissionContractService, Depends(get_permission_contract_service)
]
AuthorizationServiceDep = Annotated[AuthorizationService, Depends(get_authorization_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
RoleServiceDep = Annotated[RoleService, Depends(get_role_service)]
DepartmentServiceDep = Annotated[DepartmentService, Depends(get_department_service)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]


__all__ = [
    "ApiPermissionDependency",
    "AuthServiceDep",
    "AuthorizationServiceDep",
    "BearerTokenDep",
    "CurrentActorAllowPasswordChangeDep",
    "CurrentActorDep",
    "DbSessionDep",
    "DepartmentServiceDep",
    "DictServiceDep",
    "MfaManagementServiceDep",
    "PermissionContractServiceDep",
    "PermissionResourceServiceDep",
    "RoleDataScopeServiceDep",
    "RolePermissionServiceDep",
    "RoleServiceDep",
    "SessionManagementServiceDep",
    "SystemParamServiceDep",
    "UserServiceDep",
    "client_ip",
    "client_user_agent",
    "get_auth_service",
    "get_authenticated_session",
    "get_authorization_service",
    "get_bearer_token",
    "get_current_actor",
    "get_current_actor_allow_password_change",
    "get_department_service",
    "get_dict_service",
    "get_mfa_management_service",
    "get_permission_contract_service",
    "get_permission_resource_service",
    "get_role_data_scope_service",
    "get_role_permission_service",
    "get_role_service",
    "get_session_management_service",
    "get_session_service",
    "get_system_param_service",
    "get_user_service",
    "require_api_permission",
]
