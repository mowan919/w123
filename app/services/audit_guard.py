"""服务层审计与"拒绝必须留痕"守卫的公共实现。

为什么要抽出来
------------
Phase 2 的 `UserService` / `DepartmentService` / `RoleDataScopeService`
各自实现了一份 `_record` + `_denial_audited`。到 Phase 3 还要再加
4 个服务（Role / 资源 / 授权 / 继承），再复制 4 份必然出现"某一份漏了
某个异常类型"的漂移 —— 而这类漂移的后果是**越权尝试不留痕**，
属于安全缺陷而不是风格问题。

因此本模块把该模式收敛为单一实现，Phase 3 起的服务统一使用它。

拒绝的审计口径（与 FIX-002 一致）
------------------------------
**被拒绝的操作必须写 FAILURE 审计，且不能因为提前 `raise` 而绕过。**

- `PermissionDeniedError`（403 越权）→ 必须留痕；
- `ConflictError`（409 安全不变量 / 业务冲突，例如"继承会成环"、
  "角色仍被用户持有"）→ 同样留痕：这些是"我们**拒绝执行**了某个请求"，
  审计需要的正是这份"谁在什么时候试图做什么、为什么被拦下"。
- `NotFoundError` → **不**留痕。它是"目标不存在"，不是拒绝；
  把它记成 FAILURE 会让审计里混入正常操作（例如并发删除后的重试），
  削弱 FAILURE 的信号价值。
- `BadRequestError` → **不**留痕。参数自洽性问题属调用方错误，
  与"试图越权"信号不同。

守卫的用法约束
------------
所有身份 / 范围 / 授权 / 安全不变量校验都必须**包在守卫内**，
不得各自散落 `try/except` —— 散落写法必然漏掉某条路径
（Phase 2 就因此真实漏掉过 `DepartmentService._assert_parent_change_allowed`）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.audit import AuditAction, AuditEvent, AuditRecorder, AuditResult
from app.auth.actor import CurrentActor
from app.core.errors import ConflictError, PermissionDeniedError


class AuditGuard:
    """某类资源的审计记录器 + 拒绝守卫。

    Attributes:
        resource_type: 审计中的 `resource_type`（如 `ROLE` / `PERMISSION_RESOURCE`）。
    """

    __slots__ = ("_recorder", "_resource_type")

    def __init__(self, recorder: AuditRecorder, resource_type: str) -> None:
        self._recorder = recorder
        self._resource_type = resource_type

    @property
    def resource_type(self) -> str:
        """审计资源类型。"""
        return self._resource_type

    # ------------------------------------------------------------------
    # 记录
    # ------------------------------------------------------------------
    def success(
        self,
        *,
        actor: CurrentActor,
        action: AuditAction,
        resource_id: int | None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        """记录一条成功审计（append-only）。"""
        self._record(
            actor=actor,
            action=action,
            resource_id=resource_id,
            result=AuditResult.SUCCESS,
            before=before,
            after=after,
        )

    def denied(
        self,
        *,
        actor: CurrentActor,
        action: AuditAction,
        resource_id: int | None,
        error_code: int,
    ) -> None:
        """记录一条拒绝审计（`result = FAILURE`）。"""
        self._record(
            actor=actor,
            action=action,
            resource_id=resource_id,
            result=AuditResult.FAILURE,
            error_code=error_code,
        )

    def _record(
        self,
        *,
        actor: CurrentActor,
        action: AuditAction,
        resource_id: int | None,
        result: AuditResult,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        error_code: int | None = None,
    ) -> None:
        self._recorder.record(
            AuditEvent.build(
                action=action,
                resource_type=self._resource_type,
                resource_id=resource_id,
                operator_id=actor.user_id,
                operator_username=actor.username,
                result=result,
                before_data=before,
                after_data=after,
                error_code=error_code,
                ip=actor.ip,
                user_agent=actor.user_agent,
            )
        )

    # ------------------------------------------------------------------
    # 守卫
    # ------------------------------------------------------------------
    @contextmanager
    def denial_audited(
        self,
        *,
        actor: CurrentActor,
        action: AuditAction,
        resource_id: int | None,
    ) -> Iterator[None]:
        """把"拒绝"统一写成 FAILURE 审计（捕获类型见模块说明）。"""
        try:
            yield
        except (PermissionDeniedError, ConflictError) as exc:
            self.denied(
                actor=actor,
                action=action,
                resource_id=resource_id,
                error_code=exc.code,
            )
            raise


__all__ = ["AuditGuard"]
