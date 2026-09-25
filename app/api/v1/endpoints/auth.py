"""认证端点（Phase 4 / Spec `08 §3`）。

已实现的端点
-----------
| 方法 | 路径 | Spec 依据 |
|---|---|---|
| POST | `/auth/login` | `08 §3` |
| POST | `/auth/refresh` | `08 §3` |
| POST | `/auth/logout` | `08 §3` |
| GET | `/auth/me` | `08 §3` |
| POST | `/auth/password` | **补充端点**（见下） |
| GET | `/auth/permissions` | `08 §3` / `09 §2`（Phase 8） |

**未**实现的端点及归属（有意不做，避免预实现后续 Phase）：

- `/auth/mfa`、`/auth/mfa/verify`、`/auth/mfa/setup|enable|disable`
  → Phase 5（DD-01 具体 Provider 未冻结）；

关于 `POST /auth/password`（补充端点）
------------------------------------
Spec `08 §3` 的端点清单里**没有**改密端点，但 Spec `04 §2` 冻结了
"管理员重置后首次登录必须修改密码"。若不存在一条解除路径，
`must_change_password` 只能置 True 不能置 False —— 那不是策略，是死锁。
因此补上该端点，并已在决策台账登记（`docs/DESIGN-DECISIONS.md` INTERIM-4-03）。
Phase 2 已有同样的先例（`POST /users/{id}/delete`、`GET|PUT /users/{id}/roles`
均为人类裁定补齐）。

事务边界
-------
`app.db.session.get_db` 刻意**不**自动提交（Spec `11 §3` 需要显式事务边界）。
本模块是项目第一条 HTTP 写路径，因此在此明确约定：
**由端点负责 `commit()`** —— 端点是"一次业务操作"的边界，
而 Service 只 flush、不 commit，这样 Service 才能被安全地组合进更大的事务。

`GET /auth/permissions` 为什么不需要 API 权限位（JUDGMENT-8-02）
------------------------------------------------------------
该端点返回的是**调用者本人**的权限快照。若要求某个 API 权限位才能读取，
就会产生一个循环：客户端得先知道自己的权限，才能证明自己有权知道自己的权限；
而"没有权限"的用户会连"我没有任何权限"这件事都读不到 ——
前端只能渲染成故障页而不是"无权限页"。

它仍然**要求已认证**，且刻意使用**严格**依赖 `get_current_actor`
（处于强制改密状态的用户不可用）：强制改密状态的客户端本来就只应调用
`/auth/me` 与 `/auth/password`，此时下发权限契约等于让它先逛后台再改密。

**没有**任何"目标用户"入参 —— 目标恒为令牌所指的本人。
查看**他人**的权限属权限预览（`03 §11`），是另一条需要授权的能力，
不在本端点上开口子。

响应信封
-------
全部走 `success_response`，保证 Spec `08 §2` 的 `{code, message, data}` 一致；
失败由 `AppError` 子类经全局处理器转成同一个信封。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import (
    AuthServiceDep,
    BearerTokenDep,
    CurrentActorAllowPasswordChangeDep,
    CurrentActorDep,
    DbSessionDep,
    PermissionContractServiceDep,
    client_ip,
    client_user_agent,
)
from app.core.config import settings
from app.core.errors import TooManyRequestsError
from app.core.rate_limit import (
    RateLimitDecision,
    get_rate_limiter,
    rate_limit_headers,
)
from app.core.response import success_response
from app.core.scope import ResolvedScope
from app.core.security.password import is_password_expired
from app.db.base import utc_now
from app.models.user import AdminUser
from app.schemas.auth import (
    AuthUserResponse,
    ChangePasswordRequest,
    LoginMfaRequiredResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MeResponse,
    RefreshRequest,
    TokenPairResponse,
)
from app.schemas.mfa import MfaVerifyRequest
from app.schemas.permission_contract import (
    PermissionApiItem,
    PermissionButtonItem,
    PermissionContractResponse,
    PermissionDataScopeResponse,
    PermissionFieldItem,
    PermissionMenuItem,
    PermissionPageItem,
)
from app.services.auth import MfaPendingResult
from app.services.permission_contract import PermissionContract

router = APIRouter(tags=["Auth"])


def _user_response(user: AdminUser) -> AuthUserResponse:
    """构造登录响应中的用户摘要。"""
    return AuthUserResponse(id=user.id, username=user.username, display_name=user.display_name)


def _me_response(user: AdminUser) -> MeResponse:
    """构造 `GET /auth/me` 响应。

    `password_expired` 由**同一条**策略函数计算（`is_password_expired`），
    与登录流程共用实现 —— 若此处另行判断 90 天，两处必然漂移。
    """
    return MeResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        department_id=user.department_id,
        status=user.status,
        must_change_password=user.must_change_password,
        password_expired=is_password_expired(user.password_changed_at, now=utc_now()),
    )


#: `request.client` 缺失时（Unix socket、某些代理链路）用于限流计数的占位。
#:
#: 刻意**不是**"IP 未知就不限流" —— 那等于给"能隐藏自己来源"的调用方
#: 开一条绕过 IP 维度的通道，而这条通道恰好是攻击者最容易走的那条。
#: 代价是所有未知来源共用一个桶（可能互相牵连），
#: 相比"直接放行"这仍然是更严的选择。
UNKNOWN_CLIENT_IP = "unknown"


async def _enforce_login_rate_limit(*, username: str, ip: str) -> RateLimitDecision:
    """登录限流：**按用户名**与**按来源 IP** 各判一次。

    为什么必须两个维度（详见 `app/core/rate_limit.py`）：
    `04 §2` 的账号锁定只按账号计数，挡不住"每个账号只试一次"的撞库，
    也挡不住"反复输错把别人账号锁死"的锁定 DoS —— 两者都只有 IP
    维度能缓解；而 IP 维度挡不住分布式，所以账号维度也不能省。

    任一个超限即拒绝，且**不告诉调用方是哪个维度超限**（理由见
    `TooManyRequestsError` 的 docstring）。

    Returns:
        通过时返回该次判定的剩余配额，供响应头使用。
    """
    if not settings.rate_limit_enabled:
        return RateLimitDecision(
            allowed=True,
            limit=settings.rate_limit_login_per_subject,
            remaining=settings.rate_limit_login_per_subject,
            retry_after=0,
        )
    limiter = get_rate_limiter()
    window = settings.rate_limit_login_window_seconds
    remainings: list[int] = []

    for subject, limit in (
        (username, settings.rate_limit_login_per_subject),
        (ip, settings.rate_limit_login_per_ip),
    ):
        decision = await limiter.check(
            scope="login", subject=subject, limit=limit, window_seconds=window
        )
        if not decision.allowed:
            raise TooManyRequestsError(retry_after=decision.retry_after)
        remainings.append(decision.remaining)

    # 两个维度都通过：回显**更严格**的那个剩余量，
    # 否则客户端会以为自己还能继续撞另一个维度的墙。
    return RateLimitDecision(
        allowed=True,
        limit=settings.rate_limit_login_per_subject,
        remaining=min(remainings),
        retry_after=0,
    )


@router.post("/login", summary="登录")
async def login(
    payload: LoginRequest,
    request: Request,
    service: AuthServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """校验凭据、创建会话并签发令牌对（Spec `04 §1` 全流程）。

    失败一律返回 401 + 统一文案（Spec `10 §5`：不泄露用户是否存在）。

    口令通过但用户已绑定二次验证时，返回 **200 + `mfa_required=true`** 而不是令牌
    （DD-23 方案 A）。此时**没有**创建会话，客户端必须调用
    `POST /auth/mfa/verify` 续完登录。
    """
    ip = client_ip(request) or UNKNOWN_CLIENT_IP

    # 限流必须在**校验凭据之前**：否则它只挡住了"已经失败的请求"，
    # 对真正的攻击者没有任何成本 —— 那不叫限流，叫统计。
    quota = await _enforce_login_rate_limit(username=payload.username, ip=ip)

    result = await service.login(
        username=payload.username,
        password=payload.password.get_secret_value(),
        ip=ip,
        user_agent=client_user_agent(request),
    )
    await session.commit()

    if isinstance(result, MfaPendingResult):
        return success_response(
            LoginMfaRequiredResponse(
                mfa_required=True,
                mfa_token=result.mfa_token,
                expires_at=result.expires_at,
                provider=result.provider,
            ),
            headers=dict(rate_limit_headers(quota)),
        )

    return success_response(
        LoginResponse(
            access_token=result.tokens.access_token,
            refresh_token=result.tokens.refresh_token,
            access_expires_at=result.tokens.access_expires_at,
            refresh_expires_at=result.tokens.refresh_expires_at,
            must_change_password=result.must_change_password,
            user=_user_response(result.user),
        ),
        headers=dict(rate_limit_headers(quota)),
    )


@router.post("/mfa/verify", summary="完成登录的二次验证")
async def mfa_verify(
    payload: MfaVerifyRequest,
    request: Request,
    service: AuthServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """核销 MFA 挑战并**续完登录**（DD-23 方案 A）。

    该端点**不需要也不可能有**已认证身份：此刻还没有会话 ——
    挑战令牌就是这个事实的唯一凭证。

    成功后返回与 `POST /auth/login` **完全相同**的令牌结构：
    客户端不必为"有没有 MFA"准备两套处理逻辑，
    "登录"的最终形态始终只有一个。
    """
    ip = client_ip(request) or UNKNOWN_CLIENT_IP

    # 按来源 IP 限流。每**用户**的约束由挑战自身的尝试次数上限承担
    # （DD-23），此处不重复计数 —— 重复会让"限流"与"挑战耗尽"
    # 两个不同的语义互相干扰，出问题时分不清是哪一层拦的。
    if settings.rate_limit_enabled:
        decision = await get_rate_limiter().check(
            scope="mfa",
            subject=ip,
            limit=settings.rate_limit_mfa_per_ip,
            window_seconds=settings.rate_limit_mfa_window_seconds,
        )
        if not decision.allowed:
            raise TooManyRequestsError(retry_after=decision.retry_after)

    result = await service.complete_mfa_login(
        mfa_token=payload.mfa_token,
        code=payload.code,
        ip=ip,
        user_agent=client_user_agent(request),
    )
    await session.commit()

    return success_response(
        LoginResponse(
            access_token=result.tokens.access_token,
            refresh_token=result.tokens.refresh_token,
            access_expires_at=result.tokens.access_expires_at,
            refresh_expires_at=result.tokens.refresh_expires_at,
            must_change_password=result.must_change_password,
            user=_user_response(result.user),
        )
    )


@router.post("/refresh", summary="刷新令牌（轮换）")
async def refresh(
    payload: RefreshRequest,
    request: Request,
    service: AuthServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """用 Refresh Token 换取新的令牌对。

    每次调用都会轮换 access 与 refresh；旧 refresh 立即失效。
    若旧 refresh **再次**出现，判定为盗用并撤销整个会话（DD-02 P4），
    同时记 `AUTH_TOKEN_REUSE_DETECTED` 安全事件。
    """
    _, tokens = await service.refresh(
        refresh_token=payload.refresh_token.get_secret_value(),
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    await session.commit()

    return success_response(
        TokenPairResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            access_expires_at=tokens.access_expires_at,
            refresh_expires_at=tokens.refresh_expires_at,
        )
    )


@router.post("/logout", summary="登出")
async def logout(
    request: Request,
    token: BearerTokenDep,
    service: AuthServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """撤销当前会话（语义幂等：会话早已失效时同样返回成功）。

    刻意使用**宽松**的认证依赖（`BearerTokenDep` 而非 `CurrentActorDep`）：
    处于强制改密状态的用户必须能登出，否则会被困在改密流程里。
    """
    revoked = await service.logout(
        access_token=token,
        ip=client_ip(request),
        user_agent=client_user_agent(request),
    )
    await session.commit()

    return success_response(LogoutResponse(revoked=revoked, already_revoked=not revoked))


@router.get("/me", summary="当前用户")
async def me(
    actor: CurrentActorAllowPasswordChangeDep,
    service: AuthServiceDep,
) -> JSONResponse:
    """返回当前操作者信息。

    使用宽松依赖：客户端需要能读到 `must_change_password` 才知道该去改密 ——
    若这里就返回 403，客户端将无法发现"自己需要改密"。
    """
    user = await service.me(actor=actor)
    return success_response(_me_response(user))


def _data_scope_response(scope: ResolvedScope | None) -> PermissionDataScopeResponse:
    """把 `ResolvedScope` 映射为契约的数据范围段落。

    ⚠️ 这里有一处**极易写成 fail-open** 的映射，单独抽出来并逐分支写明：
    `department_ids` 的 `null` 表示"部门维度**不限制**"（仅 ALL / 超管），
    而"什么都看不到"必须写成 `[]`。若把"无有效角色"（`scope is None`）
    映射成 `null`，客户端会把它读成"没有部门限制" ——
    也就是把一个**全拒**状态表达成了**全放行**状态。
    这是本 Phase 的测试实际抓出来的缺陷（见结果文档 §5）。
    """
    if scope is None:
        # 无任何有效角色：既无策略，也无可见部门 → 明确的"全拒"。
        return PermissionDataScopeResponse(policy=None, department_ids=[], include_self=False)
    if scope.is_unrestricted_departments:
        return PermissionDataScopeResponse(
            policy=scope.scope, department_ids=None, include_self=scope.include_self
        )
    return PermissionDataScopeResponse(
        policy=scope.scope,
        department_ids=sorted(scope.department_ids or frozenset()),
        include_self=scope.include_self,
    )


def _contract_response(contract: PermissionContract) -> PermissionContractResponse:
    """把权限契约领域对象映射为 `09 §2` 的响应体。

    三处映射值得单独说明：

    1. **无有效角色的用户**：`context.data_scope is None` →
       `policy = null` + `department_ids = []`。
       不能用某个具体策略值顶替 —— 那会把"没配"显示成"配了最窄策略"，
       属误导性诊断（详见 `app/schemas/permission_contract.py` 的说明）。
    2. **`department_ids = null` 与 `[]` 是两件事**：
       `null` = 部门维度不限制（ALL / SUPER_ADMIN），`[]` = 全拒。
       两者在 JSON 里都"看起来像空"，因此这里显式区分，绝不互相顶替。
    3. **字段策略**取自 `context.field_policies`（已按 DD-06
       "最宽松者胜"合并），不在 HTTP 层二次合并 —— 合并规则只有一处实现。
    """
    return PermissionContractResponse(
        user_id=contract.context.user_id,
        is_super_admin=contract.context.is_super_admin,
        direct_role_ids=sorted(contract.context.direct_role_ids),
        inherited_role_ids=sorted(contract.context.inherited_role_ids),
        pages=[
            PermissionPageItem(
                id=page.id,
                code=page.resource_code,
                name=page.resource_name,
                route_path=page.route_path,
                component_path=page.component_path,
                sort_order=page.sort_order,
            )
            for page in contract.pages
        ],
        menus=[
            PermissionMenuItem(
                id=entry.resource.id,
                code=entry.resource.resource_code,
                name=entry.resource.resource_name,
                icon=entry.resource.icon,
                parent_id=entry.resource.parent_id,
                sort_order=entry.resource.sort_order,
                page_ids=list(entry.page_ids),
            )
            for entry in contract.menus
        ],
        buttons=[
            PermissionButtonItem(
                id=button.id,
                code=button.resource_code,
                name=button.resource_name,
                parent_id=button.parent_id,
                sort_order=button.sort_order,
            )
            for button in contract.buttons
        ],
        apis=[
            PermissionApiItem(
                id=api.id,
                code=api.resource_code,
                name=api.resource_name,
                api_method=api.api_method,
                api_path=api.api_path,
                parent_id=api.parent_id,
            )
            for api in contract.apis
        ],
        fields=[
            PermissionFieldItem(
                id=policy.field_id,
                code=policy.resource_code,
                field_key=policy.field_key,
                owner_resource_id=policy.owner_resource_id,
                access_level=policy.access_level,
            )
            for policy in contract.context.field_policies
        ],
        data_scope=_data_scope_response(contract.context.data_scope),
        permission_version=contract.context.version,
    )


@router.get("/permissions", summary="当前用户有效权限（前端动态权限契约）")
async def permissions(
    actor: CurrentActorDep,
    service: PermissionContractServiceDep,
) -> JSONResponse:
    """返回当前用户的有效权限（Spec `09 §2`）。

    输出 pages / menus / buttons / apis / fields / data_scope /
    permission_version，供前端**动态生成**路由、导航、按钮与字段行为。

    两条必须说清的性质：

    - 本响应**不是安全边界**（`09 §3`）。前端隐藏页面/菜单/按钮
      只是渲染策略；真正的边界是每个受保护端点的后端授权
      （`08 §10`，由 `require_api_permission` 声明式绑定）。
      因此本端点返回空列表**不会**赋予任何能力，返回了也不会替代判权。
    - 权限变更**立即生效**（`00 §1#5` / `09 §7`）：本 Phase 不启用任何
      权限缓存，每次请求实时计算，重新拉取即可看到新结果，
      不存在"改了权限但必须重新登录"的隐藏行为。

    实时计算意味着**不是**给前端做"权限快照缓存"的理由；
    客户端如需缓存，必须按 `permission_version` 自行失效。
    """
    contract = await service.build(user_id=actor.user_id)
    return success_response(_contract_response(contract))


@router.post("/password", summary="修改本人密码（含强制改密）")
async def change_password(
    payload: ChangePasswordRequest,
    actor: CurrentActorAllowPasswordChangeDep,
    service: AuthServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """修改**本人**口令（Spec `04 §2` 的"重置后首次登录强制改密"解除路径）。

    目标恒为调用者本人（由 `actor` 决定，不接受任何用户 ID 入参），
    因此不存在越权改他人密码的入口。
    """
    user = await service.change_own_password(
        actor=actor,
        current_password=payload.current_password.get_secret_value(),
        new_password=payload.new_password.get_secret_value(),
    )
    await session.commit()

    return success_response(_me_response(user))


__all__ = ["router"]
