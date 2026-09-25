"""审计日志与链路追踪端点（`08 §8`）—— **FINDING-10-01 的补救交付**。

为什么这个模块直到 Phase 10 才出现
--------------------------------
`08 §8` 冻结的这四条端点此前完全没有 HTTP 面。
Phase 6 的验收裁判（`006-logging-audit.md`）35 项**全部是落库判定**，
不含"能否读出来"，因此那次 PASS 不会暴露它 —— 与 FINDING-8-01
（Users / Departments / Roles 实体 CRUD 缺 HTTP 面）是同一类缺口：
**裁判项只判服务层，于是"HTTP 面不存在"永远判不出来**。

本模块只做接线：取数能力在 `app/services/log_query.py`。

为什么读日志也要写审计
--------------------
见 `app/audit/events.py` 中 `AUDIT_LOG_READ` 的说明：
"谁查过这份记录"是审计本身的盲区。

为什么**不**应用数据范围
----------------------
见 `ApiPermissionCode.AUDIT_READ` 的说明（INTERIM-10-01）：
五张日志表没有 `department_id`，按部门过滤会削掉跨部门操作，
而那恰恰是最需要被看见的部分。可见性只由权限位承担。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    CurrentActorDep,
    LogQueryServiceDep,
    require_api_permission,
)
from app.audit import AuditAction
from app.core.response import success_response
from app.schemas.log_query import (
    AuditLogListQuery,
    AuditLogPageResponse,
    AuditLogResponse,
    TraceDetailResponse,
    TraceListQuery,
    TracePageResponse,
)
from app.services.authorization import ApiPermissionCode

router = APIRouter()


@router.get(
    "/audit/logs",
    summary="审计日志列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.AUDIT_READ,
                action=AuditAction.AUDIT_LOG_READ,
                resource_type="AUDIT_LOG",
            )
        )
    ],
)
async def list_audit_logs(
    actor: CurrentActorDep,
    service: LogQueryServiceDep,
    query: Annotated[AuditLogListQuery, Query()],
) -> object:
    """分页检索审计日志。"""
    page = await service.list_audit_logs(
        actor=actor,
        page_num=query.pageNum,
        page_size=query.pageSize,
        action=query.action,
        operator_id=query.operator_id,
        resource_type=query.resource_type,
        resource_id=query.resource_id,
        result=str(query.result) if query.result is not None else None,
        created_from=query.created_from,
        created_to=query.created_to,
    )
    return success_response(
        AuditLogPageResponse(
            list=[AuditLogResponse.model_validate(item) for item in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@router.get(
    "/audit/logs/{audit_log_id}",
    summary="审计日志详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.AUDIT_READ,
                action=AuditAction.AUDIT_LOG_READ,
                resource_type="AUDIT_LOG",
            )
        )
    ],
)
async def get_audit_log(
    audit_log_id: int,
    actor: CurrentActorDep,
    service: LogQueryServiceDep,
) -> object:
    """读取单条审计日志（含脱敏后的 `before_data` / `after_data`）。"""
    row = await service.get_audit_log(actor=actor, audit_log_id=audit_log_id)
    return success_response(AuditLogResponse.model_validate(row))


@router.get(
    "/traces",
    summary="链路列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TRACE_READ,
                action=AuditAction.AUDIT_TRACE_READ,
                resource_type="TRACE",
            )
        )
    ],
)
async def list_traces(
    actor: CurrentActorDep,
    service: LogQueryServiceDep,
    query: Annotated[TraceListQuery, Query()],
) -> object:
    """分页列出链路摘要（按最近出现时间倒序）。"""
    page = await service.list_traces(actor=actor, page_num=query.pageNum, page_size=query.pageSize)
    return success_response(TracePageResponse.model_validate(page))


@router.get(
    "/traces/{trace_id}",
    summary="链路详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TRACE_READ,
                action=AuditAction.AUDIT_TRACE_READ,
                resource_type="TRACE",
            )
        )
    ],
)
async def get_trace(
    trace_id: str,
    actor: CurrentActorDep,
    service: LogQueryServiceDep,
) -> object:
    """回放一条链路：该 trace 上五类日志的全部条目，按时间升序。"""
    detail = await service.get_trace(actor=actor, trace_id=trace_id)
    return success_response(TraceDetailResponse.model_validate(detail))
