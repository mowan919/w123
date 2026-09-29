"""站内通知 API 契约（Pydantic DTO）—— `DESIGN-DECISIONS §32`。

Frozen / 已裁定依据
------------------
- `docs/spec/` 未定义本域，整体属技术推导（口径登记在 `§32`）。
- Spec `07 §2` / `00 §6`：API JSON 中 BIGINT 业务 ID 一律为**字符串**。
- Spec `08 §2`：响应信封 `{code, message, data}`（由端点层统一包装）。
- 人类裁定：分页请求 `pageNum` + `pageSize`，响应 `{list, total, pageNum, pageSize}`。

三个刻意的契约选择
================

1. **收件箱响应里带 `unread`（未读数），不必再发一次请求**
   角标与列表在界面上总是同时出现（面板打开时两者都要有）。
   分两次请求会让"列表里明明有一条未读、角标却是 0"这种不一致
   稳定地出现在慢网络上。多下发一个整数换来两者必然同源。

2. **没有 `is_read` 布尔字段**
   `read_at` 是**唯一真相**（时间比布尔多一个"什么时候读的"，
   见模型文档）。再加一个布尔就是第二份真相，两者不一致时无人能判谁对。
   前端判未读就是 `read_at === null`，没有回退逻辑。

3. **公告响应带 `created_by_username` 而没有 `created_by`**
   列表页要显示"谁发的"，而裸雪花 ID 在界面上毫无意义
   （这正是 `FINDING-28-01` 的类型：列里显示一串数字）。
   发布人 ID 只有在**按人检索**时才有用，那是审计的能力（`NOTIFICATION_ANNOUNCE`
   审计里带 `operator_id`），不属于本接口。

`list` 字段名遮蔽内建 `list` 的注意事项（沿用 `RolePageResponse` 的教训）
--------------------------------------------------------------------
注解与默认工厂都必须显式写 `builtins.list`，否则 Pydantic 解析注解时会在
类命名空间取到 `FieldInfo` 并报 "'FieldInfo' object is not subscriptable"。
"""

from __future__ import annotations

import builtins
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    AnnouncementAudience,
    NotificationCategory,
    NotificationLevel,
)
from app.models.notification import (
    BODY_MAX_CHARS,
    OPERATOR_USERNAME_LENGTH,
    TITLE_LENGTH,
)
from app.schemas.types import SnowflakeId

_PAGE_SIZE_MAX = 100

#: 单条标题的长度上限（与模型一致）。
_TITLE_MAX = TITLE_LENGTH


class NotificationListQuery(BaseModel):
    """`GET /auth/notifications` 查询参数。"""

    model_config = ConfigDict(extra="forbid")

    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=_PAGE_SIZE_MAX)
    unreadOnly: bool = Field(default=False, description="只看未读")
    category: NotificationCategory | None = Field(
        default=None, description="按分类过滤；不传 = 全部"
    )


class NotificationResponse(BaseModel):
    """一条站内通知。"""

    id: SnowflakeId
    category: NotificationCategory
    event_code: str | None = Field(
        default=None, description="系统事件码；公告为 null。前端据此做文案/图标分流"
    )
    announcement_id: SnowflakeId | None = Field(default=None, description="来源公告 ID")
    title: str
    body: str | None
    link: str | None = Field(default=None, description="点击后跳转的前端路由路径")
    level: NotificationLevel
    read_at: datetime | None = Field(
        default=None, description="已读时间；null = 未读（唯一判据，没有 is_read）"
    )
    created_at: datetime


class NotificationPageResponse(BaseModel):
    """收件箱分页响应。"""

    # 见模块文档：必须写 `builtins.list`，否则注解解析会在类命名空间里
    # 取到 `FieldInfo`。
    list: builtins.list[NotificationResponse] = Field(default_factory=builtins.list)
    total: int
    unread: int = Field(description="我的未读总数（与角标同源）")
    pageNum: int
    pageSize: int


class NotificationUnreadCountResponse(BaseModel):
    """角标响应（只为一个整数单独存在的端点）。

    为什么要单独一个端点而不是"取第一页顺便算"：顶栏角标是**轮询**的
    （默认 60 秒一次），轮询一个列表接口意味着每次都要读 20 行完整正文。
    这个端点只走 `ix_notifications_user_unread_active` 部分索引。
    """

    unread: int


class MarkAllReadResponse(BaseModel):
    """全部已读的结果。"""

    updated: int = Field(description="本次被标记为已读的条数（已读的不重复计数）")


class AnnouncementListQuery(BaseModel):
    """`GET /admin/notifications/announcements` 查询参数。"""

    model_config = ConfigDict(extra="forbid")

    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=_PAGE_SIZE_MAX)


class AnnouncementCreateRequest(BaseModel):
    """`POST /admin/notifications/announcements` 请求体。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=_TITLE_MAX)
    body: str | None = Field(default=None, max_length=BODY_MAX_CHARS)
    level: NotificationLevel = Field(default=NotificationLevel.INFO)
    audience_type: AnnouncementAudience = Field(
        default=AnnouncementAudience.ALL, description="ALL=全员 / ROLE=指定角色"
    )
    audience_role_id: SnowflakeId | None = Field(
        default=None, description="audience_type=ROLE 时必填；ALL 时不得传"
    )


class AnnouncementResponse(BaseModel):
    """一条已发布公告。"""

    id: SnowflakeId
    title: str
    body: str | None
    level: NotificationLevel
    audience_type: AnnouncementAudience
    audience_role_id: SnowflakeId | None
    recipient_count: int = Field(description="发布那一刻的收件人数（历史事实）")
    created_by_username: str = Field(max_length=OPERATOR_USERNAME_LENGTH)
    created_at: datetime


class AnnouncementPageResponse(BaseModel):
    """已发布公告分页响应。"""

    list: builtins.list[AnnouncementResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class AnnouncementPublishResponse(BaseModel):
    """发布结果。

    `recipient_count` 与 `announcement.recipient_count` 同源，
    单独列出是让界面能直接说"已发送给 N 人"，不必钻进嵌套对象。
    """

    announcement: AnnouncementResponse
    recipient_count: int


class AnnouncementRevokeResponse(BaseModel):
    """撤回结果。"""

    id: SnowflakeId
    purged: int = Field(description="被一并撤回的收件箱行数（已读的也会撤回）")


__all__ = [
    "AnnouncementCreateRequest",
    "AnnouncementListQuery",
    "AnnouncementPageResponse",
    "AnnouncementPublishResponse",
    "AnnouncementResponse",
    "AnnouncementRevokeResponse",
    "MarkAllReadResponse",
    "NotificationListQuery",
    "NotificationPageResponse",
    "NotificationResponse",
    "NotificationUnreadCountResponse",
]
