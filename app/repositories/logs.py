"""五类日志的落库（Spec `06 §1` / `06 §2` / `07 §8`）。

一批事件，三张表
--------------
审计事件不是"写进一个地方"，而是按类别分发：

```text
AuditEvent ─┬─→ audit_logs       （**全部**事件，保留 2 年）
            ├─→ security_logs    （SECURITY 类，保留 180 天）
            └─→ operation_logs   （OPERATION 类，保留 180 天）
```

`audit_logs` **必须先写且永远要写**：它是取证的主表，
其余两张是按保留期做的切片。因此本模块把"分类"与"写审计表"
解耦 —— 分类失败不得导致审计主记录丢失（见 `_classify_safe`）。

为什么用 Core `insert()` 而不是 ORM 对象
------------------------------------
日志是**批量追加**：一次请求可能产生十几条。ORM 实例化会带来
identity map 与 flush 顺序的开销，却换不到任何好处 ——
这些对象在被 INSERT 之后就再无用处（append-only，不会有人 update 它们）。
Core `insert()` 的 executemany 直接对应一次往返。

`id` 为什么显式生成
------------------
`PrimaryKeyMixin` 已有 Python 侧 `default=next_id`。这里仍显式传入，
是因为 Snowflake 的**单调性**恰好表达了日志需要的性质：
同一批次内后写的事件 ID 更大。若交给默认值，这一点就依赖
"SQLAlchemy 会按行序调用默认值"的实现细节，而不是明确承诺。

为什么要在边界上截断（`_clamp`）
-----------------------------
`varchar(n)` 在 PostgreSQL 下**超长即报错**。而错误发生在
`flush_logs()` 的独立事务里 —— 结果是**整批日志一起丢失**。
攻击者只要发一个 64KB 的 `User-Agent` 或超长路径，就能让这次请求
（以及同批次里其他人的日志）全部消失 —— 一条现成的**抗审计通道**。
截断只是损失一条记录的尾部，不截断则损失全部记录。
截断会在末尾留一个 `…` 标记，使"这条被截过"本身可被识别。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.buffer import FlushResult, LogBuffer
from app.audit.classify import LogCategory, classify
from app.audit.events import AuditEvent
from app.audit.records import AccessRecord, ApplicationRecord
from app.core.snowflake import next_id
from app.models.logs import (
    ACTION_LENGTH,
    IP_LENGTH,
    TRACE_ID_LENGTH,
    USER_AGENT_LENGTH,
    AccessLog,
    ApplicationLog,
    AuditLog,
    OperationLog,
    SecurityLog,
)

logger = logging.getLogger(__name__)

#: HTTP 方法列宽（``GET`` / ``OPTIONS`` 等最长为 7，留足余量）。
METHOD_LENGTH = 16

#: 请求路径列宽。路径可能被调用方任意拉长，故与 `user_agent` 同待遇。
PATH_LENGTH = 512

#: 日志级别列宽（``CRITICAL`` 为 8）。
LEVEL_LENGTH = 16

#: logger 名称列宽，与 `logging.Logger.name` 的常见上界一致。
LOGGER_LENGTH = 255

#: 截断标记。放在末尾（而不是开头）以便人眼按前缀匹配原文。
TRUNCATION_MARK = "…"

#: 失败原因在 `after_data` 中的键名（见 `app/services/auth_audit.py`）。
REASON_KEY = "reason"


def _clamp(value: str | None, limit: int) -> str | None:
    """把字符串压到列宽以内；超长时截断并追加标记。

    `None` 原样返回（可空列不许把"未知"改写成空串 ——
    空串与 NULL 在检索里语义完全不同）。
    """
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[: limit - 1] + TRUNCATION_MARK


def _text(value: str | None) -> str | None:
    """`StrEnum` → 普通 `str`，保持入库值与读回值同型。"""
    return None if value is None else str(value)


def _reason_of(event: AuditEvent) -> str | None:
    """从 `after_data["reason"]` 取失败原因（非字符串 / 缺失则为 None）。

    失败原因存放在 `after_data` 而不是新增审计字段，理由见
    `app/services/auth_audit.py`：Spec `06 §2` 的 15 个字段不可增删。
    这里只是把它**提升**为 `security_logs` 的可检索列，
    使"按 LOCKED / TOKEN_REUSE_DETECTED 检索"不必反解 JSONB。
    """
    payload = event.after_data
    if not payload:
        return None
    raw = payload.get(REASON_KEY)
    if not isinstance(raw, str):
        return None
    return _clamp(raw, ACTION_LENGTH)


def _audit_row(event: AuditEvent) -> dict[str, Any]:
    """构造 `audit_logs` 的一行（Spec `06 §2` 的 15 个字段全覆盖）。"""
    return {
        "id": next_id(),
        "trace_id": _clamp(event.trace_id, TRACE_ID_LENGTH),
        "request_id": _clamp(event.request_id, TRACE_ID_LENGTH),
        "operator_id": event.operator_id,
        "operator_username": _clamp(event.operator_username, ACTION_LENGTH),
        "action": _clamp(_text(event.action), ACTION_LENGTH),
        "resource_type": _clamp(event.resource_type, ACTION_LENGTH),
        "resource_id": event.resource_id,
        "before_data": event.before_data,
        "after_data": event.after_data,
        "result": _text(event.result),
        "error_code": event.error_code,
        "ip": _clamp(event.ip, IP_LENGTH),
        "user_agent": _clamp(event.user_agent, USER_AGENT_LENGTH),
        "created_at": event.created_at,
    }


def _shared_row(event: AuditEvent) -> dict[str, Any]:
    """构造 `security_logs` / `operation_logs` 的公共列。"""
    return {
        "id": next_id(),
        "trace_id": _clamp(event.trace_id, TRACE_ID_LENGTH),
        "request_id": _clamp(event.request_id, TRACE_ID_LENGTH),
        "operator_id": event.operator_id,
        "operator_username": _clamp(event.operator_username, ACTION_LENGTH),
        "resource_type": _clamp(event.resource_type, ACTION_LENGTH),
        "resource_id": event.resource_id,
        "result": _text(event.result),
        "error_code": event.error_code,
        "ip": _clamp(event.ip, IP_LENGTH),
        "user_agent": _clamp(event.user_agent, USER_AGENT_LENGTH),
        "created_at": event.created_at,
    }


def _security_row(event: AuditEvent) -> dict[str, Any]:
    """构造 `security_logs` 的一行（`event` 列对齐审计的 `action`）。"""
    row = _shared_row(event)
    row["event"] = _clamp(_text(event.action), ACTION_LENGTH)
    row["reason"] = _reason_of(event)
    return row


def _operation_row(event: AuditEvent) -> dict[str, Any]:
    """构造 `operation_logs` 的一行。"""
    row = _shared_row(event)
    row["action"] = _clamp(_text(event.action), ACTION_LENGTH)
    return row


def _access_row(record: AccessRecord) -> dict[str, Any]:
    """构造 `access_logs` 的一行。"""
    return {
        "id": next_id(),
        "trace_id": _clamp(record.trace_id, TRACE_ID_LENGTH),
        "request_id": _clamp(record.request_id, TRACE_ID_LENGTH),
        "operator_id": record.operator_id,
        "method": _clamp(record.method, METHOD_LENGTH),
        "path": _clamp(record.path, PATH_LENGTH),
        "status_code": record.status_code,
        "duration_ms": record.duration_ms,
        "ip": _clamp(record.ip, IP_LENGTH),
        "user_agent": _clamp(record.user_agent, USER_AGENT_LENGTH),
        "created_at": record.created_at,
    }


def _application_row(record: ApplicationRecord) -> dict[str, Any]:
    """构造 `application_logs` 的一行。"""
    return {
        "id": next_id(),
        "trace_id": _clamp(record.trace_id, TRACE_ID_LENGTH),
        "request_id": _clamp(record.request_id, TRACE_ID_LENGTH),
        "level": _clamp(record.level, LEVEL_LENGTH),
        "logger": _clamp(record.logger, LOGGER_LENGTH),
        "message": record.message,
        "created_at": record.created_at,
    }


def _classify_safe(event: AuditEvent) -> LogCategory | None:
    """分类；无法分类时**响亮地**跳过切片，而不是丢掉整批日志。

    `classify()` 对未分类动作抛 `KeyError` 是刻意的（避免静默回落），
    但它的调用点在这里 —— 若让异常冒到 `flush_logs()`，
    代价是**同一批次的所有日志一起丢失**，其中包含本该留痕的审计主记录。

    因此这里把异常收窄成"这条事件的**切片**不写"：
    审计主表照写（取证不丢），并记 ERROR 让人看得见。
    这不是静默回落 —— 静默回落是指"照样写进某个类别"且无人知晓。
    """
    try:
        return classify(event.action)
    except KeyError:
        logger.error(
            "审计动作未分类，跳过安全/操作日志切片 action=%s（审计主表仍会写入）",
            event.action,
        )
        return None


class LogRepository:
    """五类日志的仓储。**只追加**，不提供任何 update / delete。

    删除能力刻意不在这里：保留期清理要经过数据库触发器
    （`SET LOCAL vctn.retention = 'on'`），它属于 `LogRetentionService`。
    把两条路径分开，使"业务代码不可能误删审计"成为接口层面的事实。
    """

    __slots__ = ("_session",)

    def __init__(self, session: AsyncSession) -> None:
        """绑定会话。提交 / 回滚边界由调用方（`flush_logs`）掌握。"""
        self._session = session

    async def append_buffer(self, buffer: LogBuffer) -> FlushResult:
        """把一批缓冲日志写入五张表。

        Args:
            buffer: 一次请求（或兜底批次）累积的待落库日志。

        Returns:
            `FlushResult`：各类别实际写入行数；空缓冲返回全 0
                **且不发送任何 SQL**（避免为一次空请求白白占用连接）。
        """
        if buffer.is_empty():
            return FlushResult()

        audit_rows: list[dict[str, Any]] = []
        security_rows: list[dict[str, Any]] = []
        operation_rows: list[dict[str, Any]] = []

        for event in buffer.audits:
            # 审计主表无条件先写：它是取证的主记录。
            audit_rows.append(_audit_row(event))
            category = _classify_safe(event)
            if category is LogCategory.SECURITY:
                security_rows.append(_security_row(event))
            elif category is LogCategory.OPERATION:
                operation_rows.append(_operation_row(event))

        access_rows = [_access_row(record) for record in buffer.accesses]
        application_rows = [_application_row(record) for record in buffer.applications]

        if audit_rows:
            await self._session.execute(insert(AuditLog), audit_rows)
        if security_rows:
            await self._session.execute(insert(SecurityLog), security_rows)
        if operation_rows:
            await self._session.execute(insert(OperationLog), operation_rows)
        if access_rows:
            await self._session.execute(insert(AccessLog), access_rows)
        if application_rows:
            await self._session.execute(insert(ApplicationLog), application_rows)

        return FlushResult(
            audit=len(audit_rows),
            security=len(security_rows),
            operation=len(operation_rows),
            access=len(access_rows),
            application=len(application_rows),
        )


__all__ = [
    "LOGGER_LENGTH",
    "METHOD_LENGTH",
    "PATH_LENGTH",
    "TRUNCATION_MARK",
    "LogRepository",
]
