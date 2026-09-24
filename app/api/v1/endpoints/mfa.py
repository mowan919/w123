"""MFA 端点（Spec `08 §3` 的 `/auth/mfa*` 路径）。

本文件负责**管理本人 MFA** 的四个端点：

| 方法 | 路径 | 认证要求 |
|---|---|---|
| GET | `/auth/mfa` | 已认证 |
| POST | `/auth/mfa/setup` | 已认证 |
| POST | `/auth/mfa/enable` | 已认证 |
| POST | `/auth/mfa/disable` | 已认证 |

`POST /auth/mfa/verify` **不在这里** —— 它在 `auth.py`。
原因是它属于**登录流程的续完**（DD-23 第 6 步），而不是"管理我的 MFA"：
它没有调用者身份（此刻还没有会话），返回的是令牌对而不是状态。
把它并进本文件会让"需要认证"与"不可能有认证"两类端点混在一处，
从而难以一眼看出哪些端点必须挂认证依赖。

本文件**不含**任何具体算法
--------------------------------
所有算法行为都经 `MfaProvider` 协议委托。本文件、乃至整个 `app/`
都没有 TOTP / WebAuthn / SMS 的实现 —— V1 Provider 未冻结
（`00 §4` / `16 §1`），实现者不得擅自把它确定为需求事实。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import CurrentActorDep, DbSessionDep, MfaManagementServiceDep
from app.core.response import success_response
from app.models.enums import MfaStatus
from app.schemas.mfa import (
    MfaActionResponse,
    MfaCodeRequest,
    MfaSetupResponse,
    MfaStatusResponse,
)

router = APIRouter()


@router.get("/mfa", summary="查询本人的 MFA 状态")
async def status(
    actor: CurrentActorDep,
    service: MfaManagementServiceDep,
) -> JSONResponse:
    """返回当前用户的 MFA 状态（不含任何凭据材料）。

    与 `GET /auth/me` 分开的原因：MFA 状态需要一次策略解析
    （`user > role > system`），并进 `me` 会让后者的成本与失败面扩大。
    """
    view = await service.describe_status(actor=actor)
    return success_response(
        MfaStatusResponse(
            provider=view.provider,
            status=view.status,
            has_credential=view.has_credential,
            setup_at=view.setup_at,
            enabled_at=view.enabled_at,
            verified_at=view.verified_at,
            required=view.required,
            source=view.source,
        )
    )


@router.post("/mfa/setup", summary="开始绑定 MFA")
async def setup(
    actor: CurrentActorDep,
    service: MfaManagementServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """进入 `SETUP`：生成凭据并返回配网材料。

    ⚠️ 响应里的 `secret` 是**明文**，且只在此处出现一次。
    """
    result = await service.start_setup(actor=actor)
    await session.commit()
    return success_response(
        MfaSetupResponse(
            provider=result.provider,
            secret=result.secret,
            provisioning_uri=result.provisioning_uri,
        )
    )


@router.post("/mfa/enable", summary="启用 MFA（需校验一次动态码）")
async def enable(
    payload: MfaCodeRequest,
    actor: CurrentActorDep,
    service: MfaManagementServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """以一次真实校验确认"用户确实拿到了可用凭据"，再置 `ENABLED`。

    为什么必须先验一次：直接启用会让"配网失败、状态却已是 ENABLED"成为可能，
    用户下一次登录就卡在自己无法解除的二次验证上。
    """
    await service.enable(actor=actor, code=payload.code)
    await session.commit()
    return success_response(
        MfaActionResponse(provider=service.active_provider_name() or "", status=MfaStatus.ENABLED)
    )


@router.post("/mfa/disable", summary="关闭 MFA（需校验一次动态码）")
async def disable(
    payload: MfaCodeRequest,
    actor: CurrentActorDep,
    service: MfaManagementServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """关闭并清除库中的密文。

    关闭也要验一次动态码：否则"拿到会话即可关掉二次验证"会成为
    绕过 MFA 的最短路径 —— 比猜验证码容易得多。
    """
    await service.disable(actor=actor, code=payload.code)
    await session.commit()
    return success_response(
        MfaActionResponse(
            provider=service.active_provider_name() or "",
            status=MfaStatus.DISABLED,
            secret_cleared=True,
        )
    )
