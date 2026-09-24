"""会话 API 契约（Session Phase）。

Frozen / 已裁定依据
------------------
- Spec `08 §5`：`GET /sessions`、`POST /sessions/{id}/revoke`。
- Spec `08 §4`：`GET /users/{id}/sessions`、`POST /users/{id}/sessions/revoke-all`。
- Spec `04 §3`：Session 必须记录 session id / user id / login time / last active /
  IP / user agent / device / expires_at / revoked_at / revoke_reason / token identifiers。
- Spec `04 §4`：踢下线（单个 / 全部）+ SUPER_ADMIN / Department Admin 保护。
- Spec `04 §5` / `00 §5`：在线状态、在线用户查询、Session 列表/详情。
- Spec `07 §2` / `00 §6`：API JSON 中 BIGINT 业务 ID 一律为**字符串**。
- Spec `08 §2`：响应信封 `{code, message, data}`。
- 人类裁定：分页请求 `pageNum` + `pageSize`，响应 `{list, total, pageNum, pageSize}`。

关于 token 标识：**刻意不出现在响应里**
------------------------------------
`04 §3` 的 "token identifiers" 是对**表结构**的要求
（`sessions.access_token_hash` / `refresh_token_hash` 两列已满足）。
API 层既不返回明文（`10 §4`），也**不返回哈希**：

- 哈希对使用者没有任何用途（它不用于请求、不用于对账）；
- 返回它只会给"离线比对 / 撞库式确认某枚令牌是否属于某会话"提供素材。

会话在 API 中的身份由 `id` 表达，这与 `08 §5` 的路径模板 `{id}` 一致。

`online` 字段为什么必须有
----------------------
`04 §5` 要求"可查询在线用户"，而在线与否是**会话 + 用户状态的联合判定**
（见 `app.repositories.session.online_session_condition`）。
若只在查询参数上提供 `online` 过滤而不在响应中暴露判定结果，
调用方就无法回答"这个会话现在到底算不算在线"，
只能自己重新实现一遍规则 —— 那必然与后端产生第二份真相。
"""

from __future__ import annotations

import builtins
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SessionRevokeReason
from app.schemas.types import SnowflakeId

_PAGE_SIZE_MAX = 100


class SessionListQuery(BaseModel):
    """`GET /sessions` 与 `GET /users/{id}/sessions` 的查询参数。

    `pageNum` / `pageSize` 为人类裁定的驼峰命名（DD-13 未冻结），
    其余字段遵循 AGENTS.md §6 的 snake_case。
    """

    model_config = ConfigDict(extra="forbid")

    pageNum: int = Field(default=1, ge=1, description="页码，从 1 开始")
    pageSize: int = Field(default=20, ge=1, le=_PAGE_SIZE_MAX, description="每页条数，1..100")
    online: bool = Field(
        default=False,
        description=(
            "true=只返回**在线**会话（未撤销且会话总寿命未过，且所属用户为 ACTIVE）；"
            "false=不筛选，返回全部会话（含已撤销 / 已过期）。默认 false，"
            "因为会话列表的主要用途之一是排查'某个登录为什么失效了'，"
            "那种场景下恰恰需要看到已结束的会话。"
        ),
    )


class SessionResponse(BaseModel):
    """单条会话（字段覆盖 Spec `04 §3` 的全部记录项）。

    不含 `password_hash` / 令牌明文 / 令牌哈希。
    """

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId = Field(description="会话 ID（JSON 为字符串）")
    user_id: SnowflakeId = Field(description="会话所属用户 ID")
    username: str = Field(description="所属用户登录名（便于列表直接阅读）")
    display_name: str = Field(description="所属用户显示名")

    login_at: datetime = Field(description="登录时间 (UTC)")
    last_active_at: datetime = Field(description="最近活动时间 (UTC)")
    ip: str | None = Field(default=None, description="登录来源 IP")
    user_agent: str | None = Field(default=None, description="原始 User-Agent")
    device: str | None = Field(default=None, description="设备粗分类（启发式，非安全依据）")

    access_expires_at: datetime = Field(description="当前 Access Token 过期时间 (UTC)")
    refresh_expires_at: datetime = Field(description="会话总寿命上界（Refresh 过期时间, UTC)")
    revoked_at: datetime | None = Field(default=None, description="撤销时间；NULL 表示未撤销")
    revoke_reason: SessionRevokeReason | None = Field(
        default=None, description="撤销原因；与 revoked_at 同生共死"
    )
    online: bool = Field(description="当前是否在线（会话有效且所属用户为 ACTIVE）")


class SessionPageResponse(BaseModel):
    """`GET /sessions` / `GET /users/{id}/sessions` 分页响应。

    `list` 字段名由人类裁定固定，但会遮蔽内建 `list`：
    注解与默认工厂均显式走 `builtins.list`（同 `UserPageResponse`）。
    """

    model_config = ConfigDict(from_attributes=True)

    list: builtins.list[SessionResponse] = Field(default_factory=builtins.list)
    total: int = Field(description="范围内的总条数")
    pageNum: int
    pageSize: int


class SessionRevokeResponse(BaseModel):
    """`POST /sessions/{id}/revoke` 响应。

    `already_revoked` 表达**语义幂等**（DD-11 方案 A）：
    重复踢同一个会话不是错误 —— `10 §7` 要求的
    "Revoke 后 Token 必须不能继续访问"在两种情况下都已成立。
    """

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId = Field(description="被撤销的会话 ID")
    revoked: bool = Field(description="本次调用是否真正撤销了它")
    already_revoked: bool = Field(description="是否在本次调用之前就已经撤销")


class UserSessionsRevokeResponse(BaseModel):
    """`POST /users/{id}/sessions/revoke-all` 响应。"""

    model_config = ConfigDict(from_attributes=True)

    user_id: SnowflakeId = Field(description="被踢下线的用户 ID")
    revoked_count: int = Field(
        description=(
            "本次真正撤销的会话数。只统计**此前有效**的会话 —— "
            "已经撤销或已自然过期的会话既不会被重复计数，也不会被改写撤销原因"
        )
    )


__all__ = [
    "SessionListQuery",
    "SessionPageResponse",
    "SessionResponse",
    "SessionRevokeResponse",
    "UserSessionsRevokeResponse",
]
