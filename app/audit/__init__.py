"""审计模块。

Phase 2 只交付事件模型与记录端口；落库（Phase 6）见 `events.py` 的模块说明。
"""

from __future__ import annotations

from app.audit.events import (
    AuditAction,
    AuditEvent,
    AuditRecorder,
    AuditResult,
    NullAuditRecorder,
)

__all__ = [
    "AuditAction",
    "AuditEvent",
    "AuditRecorder",
    "AuditResult",
    "NullAuditRecorder",
]
