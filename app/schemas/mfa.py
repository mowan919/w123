"""MFA 相关 DTO（Spec `08 §3` 的 `/auth/mfa*` 端点）。

最重要的约束：本模块**没有任何一个字段**能承载 Secret
------------------------------------------------------
`GET /auth/mfa`（状态查询）与 `POST /auth/mfa/enable|disable`（动作结果）
都只回"状态是什么"，绝不回 `encrypted_secret`、明文 secret 或 provisioning_uri。

唯一的例外是 `MfaSetupResponse` —— 它必须把明文 secret 交给用户去配网，
否则绑定流程根本无法完成。这是**唯一**的暴露面，且只出现在 `setup` 的返回值里。
把其它接口也做成"顺带返回 secret 方便调试"，是这类系统最常见的失守方式，
因此这里明确写死：除 setup 外一律没有 secret 字段。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MfaStatus


class MfaStatusResponse(BaseModel):
    """`GET /auth/mfa` 响应。"""

    model_config = ConfigDict(from_attributes=True)

    provider: str | None = Field(
        default=None, description="当前生效的 MFA Provider；None 表示系统还没有 Provider"
    )
    status: MfaStatus = Field(description="生命周期状态 DISABLED / SETUP / ENABLED")
    has_credential: bool = Field(description="是否存在该 Provider 下的凭据行")
    setup_at: datetime | None = None
    enabled_at: datetime | None = None
    verified_at: datetime | None = None
    required: bool = Field(description="按 `04 §7` 解析后，该用户是否被要求二次验证")
    source: str = Field(
        description="最终生效的策略来源 USER / ROLE / SYSTEM / NONE（`04 §7` 的层级）"
    )


class MfaSetupResponse(BaseModel):
    """`POST /auth/mfa/setup` 响应。

    ⚠️ `secret` 是**明文**，本响应是它在整个 API 面上**唯一**出现的位置。
    它不写入任何日志或审计事件（见 `app/services/mfa_management.py` 的铁律）。
    """

    provider: str
    secret: str = Field(description="明文 Secret，仅此一次返回，用于配网")
    provisioning_uri: str = Field(description="配网 URI（由 Provider 按其算法给出）")
    status: MfaStatus = Field(default=MfaStatus.SETUP)


class MfaCodeRequest(BaseModel):
    """`POST /auth/mfa/enable` 与 `/disable` 的请求体。"""

    code: str = Field(min_length=1, max_length=256, description="动态验证码")


class MfaVerifyRequest(BaseModel):
    """`POST /auth/mfa/verify` 请求体。"""

    mfa_token: str = Field(min_length=1, max_length=256, description="登录返回的挑战令牌")
    code: str = Field(min_length=1, max_length=256, description="动态验证码")


class MfaActionResponse(BaseModel):
    """启用 / 禁用的结果。只回状态，不回任何凭据材料。"""

    provider: str
    status: MfaStatus
    secret_cleared: bool = Field(default=False, description="禁用时是否已清除库中的密文")


__all__ = [
    "MfaActionResponse",
    "MfaCodeRequest",
    "MfaSetupResponse",
    "MfaStatusResponse",
    "MfaVerifyRequest",
]
