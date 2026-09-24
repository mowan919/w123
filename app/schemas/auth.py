"""认证 API 契约（Pydantic DTO）。

Frozen / 已裁定依据
------------------
- Spec `08 §3`：`POST /auth/login`、`POST /auth/refresh`、`POST /auth/logout`、
  `GET /auth/me`（`/auth/mfa/*` 与 `/auth/permissions` 属 Phase 5 / Phase 8）。
- Spec `08 §1` Base `/api/v1/admin`；DD-02 阶段裁定认证端点独立为
  `/api/v1/auth`（见 `docs/DESIGN-DECISIONS.md` INTERIM-4-01）。
- Spec `08 §2`：响应信封 `{code, message, data}`。
- Spec `07 §2` / `00 §6`：API JSON 中 BIGINT 业务 ID 一律为**字符串**。
- Spec `10 §4`：不得记录 / 返回 password / password hash / token 明文
  （令牌是**唯一例外**：它必须返回给客户端，否则无法使用；
  因此令牌只能出现在**响应体**，绝不落日志 —— `app.core.masking`
  的 `NEVER_LOG_KEYS` 已把 `access_token` / `refresh_token` 列为永不记录）。

口令字段一律使用 `SecretStr`
--------------------------
`SecretStr` 让 `repr()` / `str()` 输出 `**********`，从而在
"异常被打印""对象被随手 log""调试器回显"这些常见路径上都不会泄漏口令。
这是 `10 §4` 在类型层面的落地，而不是靠"记得不要 log"。

`Field(max_length=...)` 只做**粗粒度拒绝**
---------------------------------------
口令长度上界仅用于挡住明显异常的输入（避免超大字符串进入 argon2）；
复杂度策略的**唯一判定点**是 `app.core.security.password`
（SSOT），schema 层不重复实现，避免两处规则漂移。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.models.enums import UserStatus
from app.schemas.types import SnowflakeId

#: 与 `admin_users.username` 列宽一致。
_USERNAME_MAX = 64
#: 口令上界（防御性；复杂度校验见 `app.core.security.password`）。
_PASSWORD_MAX = 256
#: 刷新令牌上界（`token_urlsafe(32)` 约 43 字符，留足余量）。
_TOKEN_MAX = 256


class LoginRequest(BaseModel):
    """`POST /auth/login` 请求体。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=_USERNAME_MAX, description="登录名")
    password: SecretStr = Field(
        max_length=_PASSWORD_MAX,
        description="口令；绝不回显、绝不记录（Spec 10 §4）",
    )


class RefreshRequest(BaseModel):
    """`POST /auth/refresh` 请求体。

    令牌放**请求体**（而非 `HttpOnly` Cookie）是 DD-02 P6 的裁定：
    Cookie 方案需要同时冻结 `SameSite` / `Secure` / CSRF 防护 / 多域策略，
    而本项目的前端形态尚未冻结；放进请求体只需客户端自己保存，
    服务端不引入新的 CSRF 面。
    """

    model_config = ConfigDict(extra="forbid")

    refresh_token: SecretStr = Field(
        max_length=_TOKEN_MAX,
        description="Refresh Token；每次调用都会轮换，旧令牌立即失效",
    )


class ChangePasswordRequest(BaseModel):
    """`POST /auth/password` 请求体（本人改密 / 强制改密）。

    端点补充说明：Spec `08 §3` 未列出该端点，但 `04 §2` 冻结了
    "管理员重置后首次登录必须修改密码"，而"必须修改"若无可用路径即为死锁。
    该端点为**补充端点**，已在决策台账登记（INTERIM-4-03）。
    """

    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(
        max_length=_PASSWORD_MAX,
        description="当前口令；用于防止会话被盗后直接改密",
    )
    new_password: SecretStr = Field(
        max_length=_PASSWORD_MAX,
        description="新口令；复杂度与「最近 5 个不重复」由服务端策略校验",
    )


class AuthUserResponse(BaseModel):
    """登录响应中携带的最小用户信息。

    刻意**不含** `password_hash` / `failed_login_count` / `locked_until`：
    客户端不需要它们，而返回越多越容易在某次改动中被顺手记录到日志里。
    """

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId = Field(description="用户 ID（JSON 为字符串）")
    username: str
    display_name: str


class TokenPairResponse(BaseModel):
    """一次令牌签发的结果（登录与刷新共用）。

    时间字段用**绝对时间**（`*_expires_at`）而不是 `expires_in` 秒数：
    绝对时间不受客户端时钟偏移影响，也让"会话何时结束"在前后端是同一个事实。
    """

    access_token: str = Field(description="访问令牌；放入 Authorization: Bearer")
    refresh_token: str = Field(description="刷新令牌；每次刷新都会轮换")
    token_type: Literal["Bearer"] = Field(default="Bearer")
    access_expires_at: datetime = Field(description="访问令牌过期时间 (UTC)")
    refresh_expires_at: datetime = Field(description="刷新令牌过期时间 (UTC)；固定不滑动")


class LoginResponse(TokenPairResponse):
    """`POST /auth/login` 响应。"""

    must_change_password: bool = Field(
        default=False,
        description="为 true 时客户端必须先调用 POST /auth/password，否则其他受保护接口将返回 403",
    )
    user: AuthUserResponse


class LogoutResponse(BaseModel):
    """`POST /auth/logout` 响应。

    `already_revoked = true` 表示调用前会话就已失效（并发登出 / 已过期）。
    这**不是**错误：登出的意图已经达成（DD-11 方案 A 语义幂等）。
    """

    revoked: bool = Field(description="本次调用是否真正撤销了会话")
    already_revoked: bool = Field(description="调用前会话是否已经失效")


class MeResponse(BaseModel):
    """`GET /auth/me` 响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    username: str
    display_name: str
    department_id: SnowflakeId | None = None
    status: UserStatus
    must_change_password: bool
    password_expired: bool = Field(
        default=False,
        description="口令是否已超过 90 天；与 must_change_password 可能同时为 true",
    )


__all__ = [
    "AuthUserResponse",
    "ChangePasswordRequest",
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "MeResponse",
    "RefreshRequest",
    "TokenPairResponse",
]
