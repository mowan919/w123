"""审计事件定义与记录端口。

Frozen 依据
-----------
Spec `06 §2` Audit 必须包含 15 个字段：
    audit_log_id / trace_id / request_id / operator_id / operator_username /
    action / resource_type / resource_id / before_data / after_data /
    result / error_code / ip / user_agent / created_at
Spec `10 §8`：关键安全操作必须可审计，Audit append-only。
Spec `06 §4` / `00 §8`：before_data / after_data 必须脱敏。

范围边界
-------
Audit **落库**（`audit_logs` 表、分区、retention）属于 Phase 6，
且 `16 §34#8`（DD-08 日志分区的最终实现）尚未冻结。

因此本模块在 Phase 2 只交付：
- `AuditEvent`：与 06 §2 字段一一对应的事件值对象；
- `AuditRecorder`：记录端口（Protocol）；
- `NullAuditRecorder`：默认实现，不做任何持久化。

Service 层**从一开始就通过端口调用**，Phase 6 只需替换实现，
无需改动任何业务代码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from app.core.context import get_request_id, get_trace_id
from app.db.base import utc_now


class AuditAction(StrEnum):
    """审计动作。命名 `RESOURCE_VERB`，便于按资源检索。"""

    USER_CREATE = "USER_CREATE"
    USER_READ = "USER_READ"
    USER_UPDATE = "USER_UPDATE"
    USER_DISABLE = "USER_DISABLE"
    USER_ENABLE = "USER_ENABLE"
    USER_DELETE = "USER_DELETE"
    USER_RESET_PASSWORD = "USER_RESET_PASSWORD"  # noqa: S105 - 审计动作名，非口令字面量
    USER_CHANGE_PASSWORD = "USER_CHANGE_PASSWORD"  # noqa: S105 - 审计动作名，非口令字面量
    USER_ROLE_ASSIGN = "USER_ROLE_ASSIGN"
    DEPARTMENT_CREATE = "DEPARTMENT_CREATE"
    DEPARTMENT_READ = "DEPARTMENT_READ"
    DEPARTMENT_UPDATE = "DEPARTMENT_UPDATE"
    DEPARTMENT_DISABLE = "DEPARTMENT_DISABLE"
    DEPARTMENT_DELETE = "DEPARTMENT_DELETE"


class AuditResult(StrEnum):
    """审计结果。"""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """一条审计事件（字段与 Spec 06 §2 一一对应）。"""

    action: AuditAction
    resource_type: str
    resource_id: int | None
    operator_id: int | None
    operator_username: str | None
    result: AuditResult = AuditResult.SUCCESS
    trace_id: str | None = None
    request_id: str | None = None
    before_data: dict[str, Any] | None = None
    after_data: dict[str, Any] | None = None
    error_code: int | None = None
    ip: str | None = None
    user_agent: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    audit_log_id: int | None = None

    @classmethod
    def build(
        cls,
        *,
        action: AuditAction,
        resource_type: str,
        resource_id: int | None,
        operator_id: int | None,
        operator_username: str | None,
        **kwargs: Any,
    ) -> AuditEvent:
        """构造事件并自动补齐 trace_id / request_id 上下文。

        Spec `06 §3`：Trace 必须贯穿到 Audit/Security Log。
        """
        kwargs.setdefault("trace_id", get_trace_id())
        kwargs.setdefault("request_id", get_request_id())
        return cls(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            operator_id=operator_id,
            operator_username=operator_username,
            **kwargs,
        )


class AuditRecorder(Protocol):
    """审计记录端口。"""

    def record(self, event: AuditEvent) -> None:
        """记录一条审计事件（append-only 语义）。"""
        ...


class NullAuditRecorder:
    """默认端口实现：不做任何持久化。

    用于未注入真实记录器的场景（例如纯单元测试），
    保证 Service 不因缺少审计设施而失败。
    """

    def record(self, event: AuditEvent) -> None:
        return None


__all__ = [
    "AuditAction",
    "AuditEvent",
    "AuditRecorder",
    "AuditResult",
    "NullAuditRecorder",
]
