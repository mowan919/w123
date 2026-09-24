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

**未**实现的端点及归属（有意不做，避免预实现后续 Phase）：

- `/auth/mfa`、`/auth/mfa/verify`、`/auth/mfa/setup|enable|disable`
  → Phase 5（DD-01 具体 Provider 未冻结）；
- `/auth/permissions` → Phase 8（动态权限契约：page/menu/button/api/field/data scope）。

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
    DbSessionDep,
    client_ip,
    client_user_agent,
)
from app.core.response import success_response
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
from app.services.auth import MfaPendingResult

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
    result = await service.login(
        username=payload.username,
        password=payload.password.get_secret_value(),
        ip=client_ip(request),
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
            )
        )

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
    result = await service.complete_mfa_login(
        mfa_token=payload.mfa_token,
        code=payload.code,
        ip=client_ip(request),
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
