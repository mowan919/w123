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
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import SessionRevokeReason
from app.schemas.types import SnowflakeId

_PAGE_SIZE_MAX = 100

#: 筛选用的自由文本长度上界（IP / 设备关键字）。
#:
#: 只做上限，不做格式校验：`ip` 是**模糊**匹配的一段子串（用户可能只输入
#: `192.168` 或 `10.`），`device` 匹配的是启发式粗分类与原始 UA，
#: 都不存在可判定的"合法格式"。但必须有上界 —— 未限长的 ilike 参数
#: 会退化成全表扫描 + 超长 pattern。
_IP_FILTER_MAX = 64
_DEVICE_FILTER_MAX = 128


class SessionListQuery(BaseModel):
    """`GET /sessions` 与 `GET /users/{id}/sessions` 的查询参数。

    `pageNum` / `pageSize` 为人类裁定的驼峰命名（DD-13 未冻结），
    其余字段遵循 AGENTS.md §6 的 snake_case。

    筛选条件之间是 **AND** 关系；每个字段的"不筛选"表达方式不同，
    这是刻意的，因为它决定了**默认行为**：

    | 字段 | 不筛选的取值 | 理由 |
    |---|---|---|
    | `online` | `null`（省略） | 三态：null / true / false 分别是全部 / 仅在线 / 仅离线 |
    | `ip` / `device` | `null`（省略） | 空串会被前端当成"填了但没填内容"，无法与"没填"区分 |
    | `login_from` / `login_to` | `null`（省略） | 区间两端可独立给出（只给下界 = "某天之后"） |
    """

    model_config = ConfigDict(extra="forbid")

    pageNum: int = Field(default=1, ge=1, description="页码，从 1 开始")
    pageSize: int = Field(default=20, ge=1, le=_PAGE_SIZE_MAX, description="每页条数，1..100")
    online: bool | None = Field(
        default=None,
        description=(
            "在线状态三态筛选：省略 / null=**不筛选**（返回全部会话，含已撤销与已过期）；"
            "true=仅在线（未撤销且会话总寿命未过，且所属用户为 ACTIVE）；"
            "false=仅离线 —— 在线的**补集**，即已撤销、会话总寿命已过、"
            "或所属用户不是 ACTIVE 三者之一。\n\n"
            "默认不筛选，因为会话列表的主要用途之一是排查"
            "'某个登录为什么失效了'，那种场景下恰恰需要看到已结束的会话。"
        ),
    )
    ip: str | None = Field(
        default=None,
        max_length=_IP_FILTER_MAX,
        description="按登录来源 IP **模糊**匹配（子串，大小写不敏感）",
    )
    device: str | None = Field(
        default=None,
        max_length=_DEVICE_FILTER_MAX,
        description=(
            "按设备 / User-Agent **模糊**匹配（子串）。刻意只有一个输入框："
            "操作系统与浏览器都落在 `device`（启发式粗分类）与 `user_agent`（原始串）"
            "这两个字段里，任何把「系统」与「浏览器」切开来的二分都会在真实数据上给出错误答案。"
        ),
    )
    login_from: datetime | None = Field(
        default=None, description="登录时间下界（**含**边界，ISO 8601；不带时区时按 UTC 解释）"
    )
    login_to: datetime | None = Field(
        default=None, description="登录时间上界（**含**边界，ISO 8601；不带时区时按 UTC 解释）"
    )

    @field_validator("login_from", "login_to")
    @classmethod
    def _normalize_naive_datetime(cls, value: datetime | None) -> datetime | None:
        """把不带时区的时间按 UTC 解释。

        `login_at` 是 `timestamptz`，与 naive datetime 比较时 PostgreSQL 会
        按**服务器时区**（本实例为 UTC，但不能依赖这一点）隐式转换 ——
        那等于让查询结果取决于部署环境的一个配置项。这里显式补 UTC，
        使"我传的时间"与"库里存的时间"一定是同一个参照系。
        """
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @model_validator(mode="after")
    def _check_login_range(self) -> SessionListQuery:
        """区间必须有序。

        不静默交换两端：静默纠正会让调用方以为筛选生效了，
        实际拿到的却是另一个区间 —— 空结果比"看起来正常但错的结果"好排查。
        """
        start, end = self.login_from, self.login_to
        if start is not None and end is not None and start > end:
            raise ValueError("login_from 不能晚于 login_to")
        return self


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
