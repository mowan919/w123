"""认证链路的审计记录（Phase 4）。

为什么不直接用 `AuditGuard`
--------------------------
`AuditGuard` 的入参是 `CurrentActor`，其前提是"**操作者已经确定**"。
认证链路偏偏有一大类事件发生在操作者**尚未确定**的时刻：

```text
登录失败（用户不存在 / 口令错误 / 账号被锁定 / 状态禁用）
令牌无效 / 过期 / 已撤销
```

这些失败的取证价值恰恰最高（`04 §8` 要求记录 login failure 与 lockout）。
若强行套 `AuditGuard`，就必须编造一个 `CurrentActor` ——
审计里会出现"看起来是某个用户做的"的**假记录**，比不记录更糟。

因此本模块接受显式的 `AuthOperator`（其 `user_id` / `username` 允许为 None），
把"身份未知"如实表达为 `operator_id = None`。

内部诊断原因写在哪
----------------
登录失败必须对外使用**统一文案**（Spec `10 §5`：不得泄露用户是否存在），
但审计侧必须**可诊断**（`04 §8` 要求 login failure 与 lockout 可区分）。
因此把内部原因（`BAD_PASSWORD` / `UNKNOWN_USER` / `STATUS_DISABLED` /
`LOCKED` / `TOKEN_REUSE_DETECTED` …）写入 `after_data["reason"]`。

对失败事件使用 `after_data` 是刻意的：审计的 15 个字段由 Spec `06 §2` 冻结，
**不得新增字段**；而"这次操作以什么原因失败"确实属于"结果状态"，
放入 `after_data` 既不改结构，又让失败事件可检索。

⚠️ 该原因**绝不进入 HTTP 响应体** —— 响应文案唯一来源是异常消息。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.audit import AuditAction, AuditEvent, AuditRecorder, AuditResult, NullAuditRecorder


@dataclass(frozen=True, slots=True)
class AuthOperator:
    """认证事件的"操作者"。

    与 `CurrentActor` 的区别：本类型允许身份为 None，
    用于表达"这次尝试的操作者无法确定"（用户不存在 / 令牌无效）。
    """

    user_id: int | None = None
    username: str | None = None
    ip: str | None = None
    user_agent: str | None = None

    @classmethod
    def of_user(
        cls,
        *,
        user_id: int,
        username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AuthOperator:
        """由已知用户构造。"""
        return cls(user_id=user_id, username=username, ip=ip, user_agent=user_agent)


class AuthAudit:
    """认证事件记录器。"""

    __slots__ = ("_recorder",)

    def __init__(self, recorder: AuditRecorder | None = None) -> None:
        self._recorder: AuditRecorder = recorder or NullAuditRecorder()

    def record(
        self,
        *,
        action: AuditAction,
        operator: AuthOperator,
        resource_type: str,
        resource_id: int | None = None,
        result: AuditResult = AuditResult.SUCCESS,
        reason: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        error_code: int | None = None,
    ) -> None:
        """记录一条认证事件。"""
        payload = dict(after) if after else {}
        if reason is not None:
            payload["reason"] = reason

        self._recorder.record(
            AuditEvent.build(
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                operator_id=operator.user_id,
                operator_username=operator.username,
                result=result,
                before_data=before,
                after_data=payload or None,
                error_code=error_code,
                ip=operator.ip,
                user_agent=operator.user_agent,
            )
        )

    def success(
        self,
        *,
        action: AuditAction,
        operator: AuthOperator,
        resource_type: str,
        resource_id: int | None = None,
        after: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> None:
        """记录成功事件。"""
        self.record(
            action=action,
            operator=operator,
            resource_type=resource_type,
            resource_id=resource_id,
            result=AuditResult.SUCCESS,
            reason=reason,
            after=after,
        )

    def failure(
        self,
        *,
        action: AuditAction,
        operator: AuthOperator,
        resource_type: str,
        resource_id: int | None = None,
        reason: str,
        error_code: int | None = None,
    ) -> None:
        """记录失败事件（`reason` 为内部诊断原因，不对外返回）。"""
        self.record(
            action=action,
            operator=operator,
            resource_type=resource_type,
            resource_id=resource_id,
            result=AuditResult.FAILURE,
            reason=reason,
            error_code=error_code,
        )


__all__ = ["AuthAudit", "AuthOperator"]
