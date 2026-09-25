"""非审计类日志的记录值对象（Access / Application）。

为什么与 `AuditEvent` 分开
-------------------------
`AuditEvent` 是**业务语义**事件（谁对哪个资源做了什么），由服务层产生；
本模块的两个记录是**技术语义**事件（某个 HTTP 请求 / 某条日志），
分别由中间件与 logging handler 产生。

两者共用一个落库通道（`app/audit/buffer.py` 的缓冲区 + 一次 flush），
但类型必须分开：审计事件有 `action` / `before_data`，访问日志有
`method` / `status_code`，把它们强塞进同一个类型会得到一堆互斥的可空字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.context import get_actor_id, get_request_id, get_trace_id
from app.db.base import utc_now


@dataclass(frozen=True, slots=True)
class AccessRecord:
    """一条访问日志（Spec `06 §1` Access Log，保留 30 天）。"""

    method: str
    path: str
    status_code: int
    duration_ms: int
    operator_id: int | None = None
    trace_id: str | None = None
    request_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def build(
        cls,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AccessRecord:
        """构造记录并自动补齐 trace / request / operator 上下文。

        Spec `06 §3` 要求 Trace 贯穿到日志；`operator_id` 由认证依赖写入
        上下文（未认证为 `None`），此处读取 —— 中间件不重复解析令牌。
        """
        return cls(
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            operator_id=get_actor_id(),
            trace_id=get_trace_id(),
            request_id=get_request_id(),
            ip=ip,
            user_agent=user_agent,
        )


@dataclass(frozen=True, slots=True)
class ApplicationRecord:
    """一条应用日志（Spec `06 §1` Application Log，保留 30 天）。

    `message` 必须**已脱敏**：调用方是 `app/core/logging.py::DbLogHandler`，
    它挂在 `MaskingFilter` 之后，因此进入此处时已过一遍脱敏。
    这里不重复脱敏，因为"脱敏两次"会让 `138****1234` 被再次处理成
    面目全非的串，反而破坏可读性 —— 脱敏是**一次且在最外层**的职责。
    """

    level: str
    logger: str
    message: str
    trace_id: str | None = None
    request_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def build(cls, *, level: str, logger: str, message: str) -> ApplicationRecord:
        """构造记录并自动补齐 trace / request 上下文。"""
        return cls(
            level=level,
            logger=logger,
            message=message,
            trace_id=get_trace_id(),
            request_id=get_request_id(),
        )


__all__ = ["AccessRecord", "ApplicationRecord"]
