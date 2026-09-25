"""审计日志与链路追踪的查询契约（`08 §8`）—— **FINDING-10-01 的补救交付**。

为什么这个模块直到 Phase 10 才出现
--------------------------------
`08 §8` 早就冻结了下面这组端点：

```text
GET /audit/logs
GET /audit/logs/{id}
GET /traces
GET /traces/{traceId}
```

但 Phase 6 的验收裁判（`006-logging-audit.md`，35 项）**全部是落库判定**
——五类日志写不写得进、字段齐不齐、保留期对不对——不含"能否把它们读出来"。
于是那次 PASS 时不会暴露"日志只进不出"这个缺口：
系统能**记**，却没有任何 HTTP 端点能**查**，
运维只能直连数据库。它在 Phase 10 的全量路由核对中被发现。

命名：`audit/logs` 而不是 `audit-logs`
-------------------------------------
`08 §8` 的字面路径是 `/audit/logs` 与 `/traces`，
与其他资源（`/users`、`/roles`、`/dicts`）的扁平命名不同，
但这是**冻结文本**，路径形状不属可自行统一的范畴。

为什么响应不复用 ORM 对象
------------------------
`after_data` / `before_data` 是 `JSONB`，其中的值由 `06 §4` 保证**已脱敏**。
直接把 ORM 行丢出去会把未来新增的列（例如某个内部标记列）
一并暴露 —— 日志表未来加列的概率远高于业务表（排障需求驱动）。
显式 DTO 让"对外暴露什么"成为一次**有意识的决定**。

链路条目的 `detail` 为什么是 `dict` 而不是强类型
--------------------------------------------
五张日志表的列差异是**本质**的（访问日志有 `status_code`，
应用日志有 `message`，审计日志有 `before_data`）。
强行统一成一个扁平结构要么丢信息、要么造出大量可空列 ——
后者与"日志表未来会加列"的方向正好相反。
因此取折中：公共字段（时间 / 操作者 / trace）**强类型**，
各表特有字段放进 `detail` 这个开放字典。
"""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.audit.events import AuditResult
from app.schemas.types import SnowflakeId

_PAGE_SIZE_MAX = 100


class AuditLogListQuery(BaseModel):
    """`GET /audit/logs` 查询参数。

    `pageNum` / `pageSize` 为人类裁定的驼峰命名（DD-13 未冻结），
    其余字段遵循 AGENTS.md §6 的 snake_case。

    为什么只提供"等值 + 时间区间"过滤
    ------------------------------
    审计检索的典型问法是"某个动作在某段时间内由谁做过"。
    刻意**不**提供 `keyword` 之类的模糊匹配：日志正文是 `JSONB`，
    模糊匹配会退化成全表扫描，而审计表是**增长最快**的表（2 年留存）。
    等值过滤能命中既有索引（`ix_audit_logs_action_created_at` 等），
    模糊匹配不能 —— 那会让一个"查日志"的接口成为压垮数据库的入口。
    """

    model_config = ConfigDict(extra="forbid")

    pageNum: int = Field(default=1, ge=1, description="页码，从 1 开始")
    pageSize: int = Field(default=20, ge=1, le=_PAGE_SIZE_MAX, description="每页条数，1..100")

    action: str | None = Field(default=None, max_length=64, description="按审计动作等值过滤")
    operator_id: SnowflakeId | None = Field(default=None, description="按操作者用户 ID 过滤")
    resource_type: str | None = Field(
        default=None, max_length=64, description="按资源类型过滤（如 USER / ROLE）"
    )
    resource_id: SnowflakeId | None = Field(default=None, description="按资源 ID 过滤")
    result: AuditResult | None = Field(default=None, description="按结果过滤（SUCCESS / FAILURE）")
    created_from: datetime | None = Field(default=None, description="起始时间（含），UTC")
    created_to: datetime | None = Field(default=None, description="结束时间（含），UTC")


class AuditLogResponse(BaseModel):
    """单条审计日志，字段与 Spec `06 §2` **一一对应**（15 项）。

    `before_data` / `after_data` 已在**入缓冲时**脱敏（`app/audit/buffer.py`），
    这里不再二次处理 —— 二次处理会让"已脱敏"这件事的责任边界变模糊。
    """

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId = Field(description="审计日志 ID（JSON 为字符串）")
    trace_id: str | None = Field(default=None, description="链路追踪 ID")
    request_id: str | None = Field(default=None, description="请求 ID")
    operator_id: SnowflakeId | None = Field(default=None, description="操作者用户 ID")
    operator_username: str | None = Field(default=None, description="操作者登录名")
    action: str = Field(description="审计动作")
    resource_type: str = Field(description="资源类型")
    resource_id: SnowflakeId | None = Field(default=None, description="资源 ID")
    before_data: dict[str, Any] | None = Field(default=None, description="变更前数据（**已脱敏**）")
    after_data: dict[str, Any] | None = Field(default=None, description="变更后数据（**已脱敏**）")
    result: str = Field(description="结果 SUCCESS / FAILURE")
    error_code: int | None = Field(default=None, description="失败时的业务错误码")
    ip: str | None = Field(default=None, description="来源 IP")
    user_agent: str | None = Field(default=None, description="User-Agent")
    created_at: datetime = Field(description="发生时间 (UTC)")


class AuditLogPageResponse(BaseModel):
    """`GET /audit/logs` 分页响应（人类裁定：`{list,total,pageNum,pageSize}`）。"""

    model_config = ConfigDict(from_attributes=True)

    list: builtins.list[AuditLogResponse] = Field(default_factory=builtins.list)
    total: int = Field(description="过滤后的总条数")
    pageNum: int
    pageSize: int


class TraceListQuery(BaseModel):
    """`GET /traces` 查询参数。"""

    model_config = ConfigDict(extra="forbid")

    pageNum: int = Field(default=1, ge=1, description="页码，从 1 开始")
    pageSize: int = Field(default=20, ge=1, le=_PAGE_SIZE_MAX, description="每页条数，1..100")


class TraceSummaryResponse(BaseModel):
    """一条链路的**摘要**（`GET /traces` 的一行）。

    只给"定位一次请求所需的最小信息"：trace id、首次/末次出现时间、
    五类日志各自的条数。详情由 `GET /traces/{traceId}` 给出 ——
    列表接口返回全部正文会让"翻一页链路"变成拉全表。
    """

    model_config = ConfigDict(from_attributes=True)

    trace_id: str = Field(description="链路追踪 ID")
    request_id: str | None = Field(default=None, description="该链路上最近见到的请求 ID")
    first_seen_at: datetime = Field(description="该链路最早一条日志的时间 (UTC)")
    last_seen_at: datetime = Field(description="该链路最晚一条日志的时间 (UTC)")
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="按日志类别的条数：access / audit / security / operation / application",
    )
    total_entries: int = Field(description="该链路上的日志总条数")


class TracePageResponse(BaseModel):
    """`GET /traces` 分页响应。"""

    model_config = ConfigDict(from_attributes=True)

    list: builtins.list[TraceSummaryResponse] = Field(default_factory=builtins.list)
    total: int = Field(description="链路总数")
    pageNum: int
    pageSize: int


class TraceEntryResponse(BaseModel):
    """链路上的**一条**日志（`GET /traces/{traceId}` 的一行）。

    `log_type` 说明它来自五张表中的哪一张；
    `detail` 承载该表特有的列（见本模块文档的理由）。
    """

    model_config = ConfigDict(from_attributes=True)

    log_type: str = Field(
        description="日志类别：access / audit / security / operation / application"
    )
    id: SnowflakeId = Field(description="该日志在其所属表中的主键")
    trace_id: str = Field(description="链路追踪 ID")
    request_id: str | None = Field(default=None, description="请求 ID")
    created_at: datetime = Field(description="发生时间 (UTC)")
    operator_id: SnowflakeId | None = Field(default=None, description="操作者用户 ID")
    operator_username: str | None = Field(default=None, description="操作者登录名")
    name: str = Field(description="该条日志的标题（动作名 / 事件名 / `方法 路径` / `级别 logger`）")
    result: str | None = Field(default=None, description="结果；访问日志以状态码字符串表达")
    detail: dict[str, Any] = Field(
        default_factory=dict, description="该日志类别特有的字段（已脱敏）"
    )


class TraceDetailResponse(BaseModel):
    """`GET /traces/{traceId}` 响应。

    为什么不是分页：一次请求的日志条数有天然上界（十几条量级），
    且"看清一次请求做过什么"要求它们**一起**返回 ——
    分页会让调用方为了还原全貌而反复翻页，期间数据还可能被保留期清理掉。
    条数上界由服务层的 `*_MAX` 常量兜住。
    """

    model_config = ConfigDict(from_attributes=True)

    trace_id: str = Field(description="链路追踪 ID")
    entries: builtins.list[TraceEntryResponse] = Field(
        default_factory=builtins.list, description="按时间升序排列的全部日志条目"
    )


__all__ = [
    "AuditLogListQuery",
    "AuditLogPageResponse",
    "AuditLogResponse",
    "TraceDetailResponse",
    "TraceEntryResponse",
    "TraceListQuery",
    "TracePageResponse",
    "TraceSummaryResponse",
]
