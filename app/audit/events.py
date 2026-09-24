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
    ROLE_CREATE = "ROLE_CREATE"
    ROLE_READ = "ROLE_READ"
    ROLE_UPDATE = "ROLE_UPDATE"
    ROLE_DELETE = "ROLE_DELETE"
    ROLE_DATA_SCOPE_READ = "ROLE_DATA_SCOPE_READ"
    ROLE_DATA_SCOPE_UPDATE = "ROLE_DATA_SCOPE_UPDATE"
    ROLE_PERMISSION_READ = "ROLE_PERMISSION_READ"
    ROLE_PERMISSION_UPDATE = "ROLE_PERMISSION_UPDATE"
    ROLE_INHERITANCE_GRANT = "ROLE_INHERITANCE_GRANT"
    ROLE_INHERITANCE_REVOKE = "ROLE_INHERITANCE_REVOKE"
    PERMISSION_RESOURCE_CREATE = "PERMISSION_RESOURCE_CREATE"
    PERMISSION_RESOURCE_READ = "PERMISSION_RESOURCE_READ"
    PERMISSION_RESOURCE_UPDATE = "PERMISSION_RESOURCE_UPDATE"
    PERMISSION_RESOURCE_DELETE = "PERMISSION_RESOURCE_DELETE"
    PERMISSION_PREVIEW = "PERMISSION_PREVIEW"

    # ---- Phase 4：认证与会话（严格对应 Spec `04 §8` 的安全日志清单） ----
    #
    # `04 §8` 要求记录：
    #   login success / login failure / lockout / password reset / password change /
    #   MFA setup·enable·disable·failure / session revoke。
    #
    # 与既有动作的对应关系（**刻意不新增重复事件**）：
    #   - password reset   → 复用 Phase 2 的 `USER_RESET_PASSWORD`
    #   - password change  → 复用 Phase 2 的 `USER_CHANGE_PASSWORD`
    #     （无论是管理员重置还是本人改密，该动作都表达"口令被修改"，
    #       再新增一个 AUTH_* 同义事件只会让安全日志出现重复记录）
    #   - session revoke   → 加下文的 `AUTH_LOGOUT`（仅本人登出）
    AUTH_LOGIN_SUCCESS = "AUTH_LOGIN_SUCCESS"
    AUTH_LOGIN_FAILURE = "AUTH_LOGIN_FAILURE"
    AUTH_LOCKOUT = "AUTH_LOCKOUT"
    #: 仅本人 logout（`04 §4`"仅本人 logout"）。管理员踢出会话属 Session Phase。
    AUTH_LOGOUT = "AUTH_LOGOUT"
    #: 检测到已轮换的 Refresh Token 被复用（DD-02 P4：family revocation）。
    #: 这不是 `04 §8` 列举的事件，而是 DD-02 冻结后**必须**可观测的安全信号：
    #: 该事件意味着"某个会话的令牌可能已被窃取"，比普通登录失败严重得多。
    AUTH_TOKEN_REUSE_DETECTED = "AUTH_TOKEN_REUSE_DETECTED"  # noqa: S105 - 审计动作名
    #: `04 §8` 的 session revoke（管理员踢出，Session Phase 产生事件）。
    AUTH_SESSION_REVOKE = "AUTH_SESSION_REVOKE"
    #: `04 §8` 的 MFA 四类事件。Phase 4 只落地登录流程中的 MFA 步骤与策略解析
    #: （DD-01 方案 A），具体 Provider 未冻结 → 事件枚举先行登记，
    #: 由 Phase 5（MFA）产生实际事件。
    MFA_SETUP = "MFA_SETUP"
    MFA_ENABLE = "MFA_ENABLE"
    MFA_DISABLE = "MFA_DISABLE"
    MFA_FAILURE = "MFA_FAILURE"


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
