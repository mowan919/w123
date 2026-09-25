"""审计日志与链路追踪的查询服务（`08 §8`）。

授权与数据范围的分工（INTERIM-10-01）
----------------------------------
本服务**不做**数据范围过滤，原因见
`ApiPermissionCode.AUDIT_READ` 的说明：五张日志表没有 `department_id`，
"按操作者部门过滤审计"会把跨部门操作（最需要看见的那些）过滤掉。
可见性完全由路由级的 `AUDIT_READ` / `TRACE_READ` 权限位承担。

本服务仍然**做**两件事：
1. 成功读取写审计（`AUDIT_LOG_READ` / `AUDIT_TRACE_READ`）——
   见 `app/audit/events.py` 中"读日志为什么要留痕"的理由；
2. 参数兜底校验（服务是公共入口，`page_size=10**9` 会退化成全表扫描）。

归一化为什么放在服务层而不是仓储层
--------------------------------
仓储返回的是"行 + 它来自哪张表"，把它翻译成 `TraceEntryResponse`
需要知道**业务语义**（访问日志的标题是 `方法 路径`，应用日志的是 `级别 logger`）。
那是服务层的职责边界；仓储只负责取数。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, NotFoundError
from app.models.logs import (
    AccessLog,
    ApplicationLog,
    AuditLog,
    OperationLog,
    SecurityLog,
)
from app.repositories.log_query import LogQueryRepository
from app.schemas.log_query import (
    TraceDetailResponse,
    TraceEntryResponse,
    TracePageResponse,
    TraceSummaryResponse,
)
from app.services.audit_guard import AuditGuard

#: 资源类型（审计的 `resource_type` 列取值）。
AUDIT_RESOURCE_TYPE = "AUDIT_LOG"
TRACE_RESOURCE_TYPE = "TRACE"

_PAGE_SIZE_MAX = 100


@dataclass(frozen=True, slots=True)
class AuditLogPage:
    """审计日志分页结果。"""

    items: list[AuditLog]
    total: int
    page_num: int
    page_size: int


class LogQueryService:
    """日志检索（审计日志 + 链路回放）。"""

    def __init__(self, session: AsyncSession, *, audit: AuditRecorder) -> None:
        self._session = session
        self._logs = LogQueryRepository(session)
        self._audit_logs = AuditGuard(audit, AUDIT_RESOURCE_TYPE)
        self._traces = AuditGuard(audit, TRACE_RESOURCE_TYPE)

    # ------------------------------------------------------------------
    # 审计日志
    # ------------------------------------------------------------------
    async def list_audit_logs(
        self,
        *,
        actor: CurrentActor,
        page_num: int = 1,
        page_size: int = 20,
        action: str | None = None,
        operator_id: int | None = None,
        resource_type: str | None = None,
        resource_id: int | None = None,
        result: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> AuditLogPage:
        """分页读取审计日志。

        Raises:
            BadRequestError: 分页参数越界，或时间区间自相矛盾。
        """
        _validate_paging(page_num=page_num, page_size=page_size)
        _validate_range(created_from=created_from, created_to=created_to)

        items, total = await self._logs.list_audit_logs(
            action=action,
            operator_id=operator_id,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            created_from=created_from,
            created_to=created_to,
            offset=(page_num - 1) * page_size,
            limit=page_size,
        )
        self._audit_logs.success(
            actor=actor,
            action=AuditAction.AUDIT_LOG_READ,
            resource_id=None,
            after={
                "scope": "LIST",
                "page_num": page_num,
                "page_size": page_size,
                "total": total,
                "filters": _filters(
                    action=action,
                    operator_id=operator_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    result=result,
                    created_from=created_from,
                    created_to=created_to,
                ),
            },
        )
        return AuditLogPage(items=list(items), total=total, page_num=page_num, page_size=page_size)

    async def get_audit_log(self, *, actor: CurrentActor, audit_log_id: int) -> AuditLog:
        """读取单条审计日志。

        Raises:
            NotFoundError: 该 ID 不存在。
        """
        row = await self._logs.get_audit_log(audit_log_id)
        if row is None:
            # 不存在**不**写 FAILURE 审计：与既有服务同口径
            # （`NotFoundError` 不是拒绝，见 `AuditGuard` 的文档）。
            raise NotFoundError("审计日志不存在")
        self._audit_logs.success(
            actor=actor,
            action=AuditAction.AUDIT_LOG_READ,
            resource_id=audit_log_id,
            after={"scope": "DETAIL"},
        )
        return row

    # ------------------------------------------------------------------
    # 链路
    # ------------------------------------------------------------------
    async def list_traces(
        self, *, actor: CurrentActor, page_num: int = 1, page_size: int = 20
    ) -> TracePageResponse:
        """分页列出链路摘要。"""
        _validate_paging(page_num=page_num, page_size=page_size)
        summaries, total = await self._logs.list_traces(
            offset=(page_num - 1) * page_size, limit=page_size
        )
        self._traces.success(
            actor=actor,
            action=AuditAction.AUDIT_TRACE_READ,
            resource_id=None,
            after={"scope": "LIST", "page_num": page_num, "page_size": page_size, "total": total},
        )
        return TracePageResponse(
            list=[
                TraceSummaryResponse(
                    trace_id=item.trace_id,
                    request_id=item.request_id,
                    first_seen_at=item.first_seen_at,
                    last_seen_at=item.last_seen_at,
                    counts=dict(item.counts),
                    total_entries=item.total_entries,
                )
                for item in summaries
            ],
            total=total,
            pageNum=page_num,
            pageSize=page_size,
        )

    async def get_trace(self, *, actor: CurrentActor, trace_id: str) -> TraceDetailResponse:
        """回放一条链路（该 trace 上的全部日志，按时间升序）。

        Raises:
            NotFoundError: 该 trace 上没有任何日志。
        """
        if not trace_id.strip():
            raise BadRequestError("traceId 不能为空")
        raw = await self._logs.get_trace_entries(trace_id)
        if not raw:
            raise NotFoundError("链路不存在")

        self._traces.success(
            actor=actor,
            action=AuditAction.AUDIT_TRACE_READ,
            resource_id=None,
            after={"scope": "DETAIL", "trace_id": trace_id, "entries": len(raw)},
        )
        return TraceDetailResponse(
            trace_id=trace_id,
            entries=[_normalize(entry) for entry in raw],
        )


def _validate_paging(*, page_num: int, page_size: int) -> None:
    """分页参数兜底校验（与 `SessionManagementService` 同口径）。"""
    if page_num < 1:
        raise BadRequestError("pageNum 必须大于等于 1")
    if not 1 <= page_size <= _PAGE_SIZE_MAX:
        raise BadRequestError(f"pageSize 必须在 1..{_PAGE_SIZE_MAX} 之间")


def _validate_range(*, created_from: datetime | None, created_to: datetime | None) -> None:
    """时间区间自洽性。

    为什么必须显式检查而不是交给 SQL：`created_from > created_to` 时
    SQL 会**安静地返回 0 行**，调用方无法区分"真的没有数据"与
    "我把时间写反了"。后者在排障现场尤其贵 —— 结论会被当成"没发生过"。
    """
    if created_from is not None and created_to is not None and created_from > created_to:
        raise BadRequestError("created_from 不能晚于 created_to")


def _filters(**kwargs: Any) -> dict[str, Any]:
    """只把**非空**过滤条件写进审计，避免审计正文被一堆 null 塞满。"""
    return {key: str(value) for key, value in kwargs.items() if value is not None}


def _normalize(entry: dict[str, Any]) -> TraceEntryResponse:
    """把"某张表的一行"归一成链路条目。

    分支按 `log_type` 而不是 `isinstance`：仓储返回时已经明确记录了
    行的来源表，用它分派比"猜它是哪个 ORM 类"更直白，
    也不会在将来两个模型恰好结构相同时分错。

    每个分支用**不同的局部变量名**：mypy 会按第一次赋值推断 `row` 的类型，
    复用同一个名字会让后续分支的 `cast` 变成"给 AccessLog 赋 OperationLog"。
    同理，`cast` 而不是 `assert isinstance` —— 断言在 `-O` 下会被移除，
    而这里的类型来源（仓储的 `log_type` ↔ 模型对应关系）是内部不变量，
    不需要运行时保护。
    """
    log_type = str(entry["log_type"])

    if log_type == "access":
        access = cast(AccessLog, entry["row"])
        return TraceEntryResponse(
            log_type=log_type,
            id=access.id,
            trace_id=access.trace_id or "",
            request_id=access.request_id,
            created_at=access.created_at,
            operator_id=access.operator_id,
            operator_username=None,
            name=f"{access.method} {access.path}",
            result=str(access.status_code),
            detail={
                "status_code": access.status_code,
                "duration_ms": access.duration_ms,
                "ip": access.ip,
                "user_agent": access.user_agent,
            },
        )
    if log_type == "audit":
        audit = cast(AuditLog, entry["row"])
        return TraceEntryResponse(
            log_type=log_type,
            id=audit.id,
            trace_id=audit.trace_id or "",
            request_id=audit.request_id,
            created_at=audit.created_at,
            operator_id=audit.operator_id,
            operator_username=audit.operator_username,
            name=str(audit.action),
            result=str(audit.result),
            detail={
                "resource_type": audit.resource_type,
                "resource_id": audit.resource_id,
                "before_data": audit.before_data,
                "after_data": audit.after_data,
                "error_code": audit.error_code,
                "ip": audit.ip,
                "user_agent": audit.user_agent,
            },
        )
    if log_type == "security":
        security = cast(SecurityLog, entry["row"])
        return TraceEntryResponse(
            log_type=log_type,
            id=security.id,
            trace_id=security.trace_id or "",
            request_id=security.request_id,
            created_at=security.created_at,
            operator_id=security.operator_id,
            operator_username=security.operator_username,
            name=str(security.event),
            result=str(security.result),
            detail={
                "resource_type": security.resource_type,
                "resource_id": security.resource_id,
                "reason": security.reason,
                "error_code": security.error_code,
                "ip": security.ip,
                "user_agent": security.user_agent,
            },
        )
    if log_type == "operation":
        operation = cast(OperationLog, entry["row"])
        return TraceEntryResponse(
            log_type=log_type,
            id=operation.id,
            trace_id=operation.trace_id or "",
            request_id=operation.request_id,
            created_at=operation.created_at,
            operator_id=operation.operator_id,
            operator_username=operation.operator_username,
            name=str(operation.action),
            result=str(operation.result),
            detail={
                "resource_type": operation.resource_type,
                "resource_id": operation.resource_id,
                "error_code": operation.error_code,
                "ip": operation.ip,
                "user_agent": operation.user_agent,
            },
        )
    application = cast(ApplicationLog, entry["row"])
    return TraceEntryResponse(
        log_type=log_type,
        id=application.id,
        trace_id=application.trace_id or "",
        request_id=application.request_id,
        created_at=application.created_at,
        operator_id=None,
        operator_username=None,
        name=f"{application.level} {application.logger}",
        result=application.level,
        detail={"message": application.message},
    )


__all__ = [
    "AUDIT_RESOURCE_TYPE",
    "TRACE_RESOURCE_TYPE",
    "AuditLogPage",
    "LogQueryService",
]
