"""日志的**读**侧（`08 §8`：审计检索与链路回放）。

为什么单独一个模块而不是加进 `LogRepository`
----------------------------------------
`app/repositories/logs.py` 的定位是**落库**（它的模块文档第一句就是
"五类日志的落库"），全部方法围绕 `insert()` 与批量追加。
读取关心的是另一组问题：过滤条件能不能命中索引、
返回多少行、跨五张表怎么归并。把两种关注点塞进一个类，
结果是任何一个改动都要读完 300 行才能确认没有影响另一半。

链路回放为什么是**五次查询**而不是一条 `UNION ALL`
--------------------------------------------
五张表的列集合不同（`access_logs` 有 `status_code`，
`application_logs` 有 `message`，`audit_logs` 有 `before_data`）。
用 `UNION ALL` 归一化需要为每张表补 `cast(None, ...)` 的空列，
那会把"这张表没有这个字段"从**类型系统**里抹掉
（SQLAlchemy 侧得到的是一个全是 `Any` 的行）。
五次查询 + Python 归并换取的是：每一张表的列仍然**被类型检查**，
且每张表各自走自己的 `ix_*_trace_id` / `created_at` 索引。

代价是 5 次往返而不是 1 次。链路回放是**排障路径**（低频、单人），
不是热路径；而审计表是增长最快的表，把查询写成能走索引的形式
比省下 4 次往返重要得多。

为什么每张表都要有行数上界
------------------------
一次请求的日志条数通常是十几条，但 `application_logs` 在
`DEBUG` 级别下一次请求可以产生上百条。若不加限制，
一个"碰巧打了很多日志的 trace"会把整个响应撑爆 ——
而truncate 掉一部分会让"看清一次请求做过什么"这个目标落空，
因此上界取一个足够大的常数并在**服务层**声明它（截断是可观测的：
响应条数 == 上界时调用方知道要看更细的来源）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.logs import (
    AccessLog,
    ApplicationLog,
    AuditLog,
    OperationLog,
    SecurityLog,
)

#: 单张表在一次链路回放中最多取多少条。
#:
#: 取值理由：一次请求的 `application_logs` 在 DEBUG 下可能上百条，
#: 而一次**业务**请求有意义的日志远不到这个数。取 500 既能容纳
#: 极端情况，又把单表返回量压在可控范围内（500 × 5 表 = 2500 条上界）。
TRACE_ENTRY_LIMIT_PER_TABLE = 500

#: 链路列表里"最近出现时间"的排序方向（最近发生的在最前）。
_TRACE_ORDER_DESC = "DESC"


class TraceSummary:
    """一条链路的聚合结果（SQL 侧 `GROUP BY trace_id` 的产物）。

    不是 ORM 对象：`GET /traces` 的结果**不来自任何一张表**，
    它是五张表的一次聚合。给它编一个假 ORM 类会让人误以为可以 `update` 它。
    """

    __slots__ = ("counts", "first_seen_at", "last_seen_at", "request_id", "trace_id")

    def __init__(
        self,
        *,
        trace_id: str,
        request_id: str | None,
        first_seen_at: datetime,
        last_seen_at: datetime,
        counts: dict[str, int],
    ) -> None:
        self.trace_id = trace_id
        self.request_id = request_id
        self.first_seen_at = first_seen_at
        self.last_seen_at = last_seen_at
        self.counts = counts

    @property
    def total_entries(self) -> int:
        """该链路上的日志总条数。"""
        return sum(self.counts.values())


class LogQueryRepository:
    """日志检索（只读）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 审计日志
    # ------------------------------------------------------------------
    async def list_audit_logs(
        self,
        *,
        action: str | None = None,
        operator_id: int | None = None,
        resource_type: str | None = None,
        resource_id: int | None = None,
        result: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[AuditLog], int]:
        """按过滤条件分页读取审计日志。

        过滤条件**只**加在能命中索引的列上（见 `AuditLogListQuery` 的理由）。
        排序固定为 `created_at DESC`：审计检索的默认问法是"最近发生了什么"，
        且 `ix_audit_logs_created_at` 正好支持这个方向。
        """
        conditions: list[Any] = []
        if action is not None:
            conditions.append(AuditLog.action == action)
        if operator_id is not None:
            conditions.append(AuditLog.operator_id == operator_id)
        if resource_type is not None:
            conditions.append(AuditLog.resource_type == resource_type)
        if resource_id is not None:
            conditions.append(AuditLog.resource_id == resource_id)
        if result is not None:
            conditions.append(AuditLog.result == result)
        if created_from is not None:
            conditions.append(AuditLog.created_at >= created_from)
        if created_to is not None:
            conditions.append(AuditLog.created_at <= created_to)

        total = await self._count(AuditLog, conditions)
        stmt = (
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = await self._session.execute(stmt)
        return rows.scalars().unique().all(), total

    async def get_audit_log(self, audit_log_id: int) -> AuditLog | None:
        """按主键读取单条审计日志。"""
        return await self._session.get(AuditLog, audit_log_id)

    async def _count(self, model: type[Any], conditions: Sequence[Any]) -> int:
        """计数（`COUNT(*)` 而不是取回全部行再 `len()`）。"""
        stmt = select(func.count()).select_from(model).where(*conditions)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    # ------------------------------------------------------------------
    # 链路
    # ------------------------------------------------------------------
    async def list_traces(
        self, *, offset: int = 0, limit: int = 20
    ) -> tuple[list[TraceSummary], int]:
        """列出出现过日志的链路（按最近出现时间倒序）。

        实现：五张表 `UNION ALL` 出 `(log_type, trace_id, request_id, created_at)`，
        再在外层 `GROUP BY trace_id` 聚合出首次 / 末次时间与分类计数。

        为什么 `UNION ALL` 而不是 `UNION`：这里要去重的是 `trace_id`，
        不是整行 —— 同一条日志不可能在两张表里出现（五张表是**分发**关系，
        不是复制关系），因此 `UNION` 的去重只会白白多一次排序。
        """
        parts = [
            self._trace_rows("access", AccessLog),
            self._trace_rows("audit", AuditLog),
            self._trace_rows("security", SecurityLog),
            self._trace_rows("operation", OperationLog),
            self._trace_rows("application", ApplicationLog),
        ]
        unioned = union_all(*parts).subquery()

        total_stmt = select(func.count()).select_from(
            select(unioned.c.trace_id).group_by(unioned.c.trace_id).subquery()
        )
        total = int((await self._session.execute(total_stmt)).scalar_one())

        agg_stmt = (
            select(
                unioned.c.trace_id,
                func.min(unioned.c.created_at).label("first_seen_at"),
                func.max(unioned.c.created_at).label("last_seen_at"),
                *[
                    func.count().filter(unioned.c.log_type == name).label(f"c_{name}")
                    for name in ("access", "audit", "security", "operation", "application")
                ],
            )
            .group_by(unioned.c.trace_id)
            .order_by(func.max(unioned.c.created_at).desc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._session.execute(agg_stmt)).all()

        # `request_id` 单独取：它不参与聚合（同一链路上每条日志可能不同），
        # 语义上取"最近一条日志的 request_id"，因此不能用 `min`/`max` 近似。
        # 一次批量查询而不是 N+1（N = 本页链路数）。
        trace_ids = [str(row.trace_id) for row in rows]
        request_ids = await self._latest_request_ids(trace_ids)

        summaries = [
            TraceSummary(
                trace_id=str(row.trace_id),
                request_id=request_ids.get(str(row.trace_id)),
                first_seen_at=row.first_seen_at,
                last_seen_at=row.last_seen_at,
                counts={
                    "access": int(row.c_access),
                    "audit": int(row.c_audit),
                    "security": int(row.c_security),
                    "operation": int(row.c_operation),
                    "application": int(row.c_application),
                },
            )
            for row in rows
        ]
        return summaries, total

    def _trace_rows(self, name: str, model: type[Any]) -> Select[Any]:
        """一张表在链路聚合中的投影。"""
        return select(
            literal(name).label("log_type"),
            model.trace_id.label("trace_id"),
            model.request_id.label("request_id"),
            model.created_at.label("created_at"),
        ).where(model.trace_id.is_not(None))

    async def _latest_request_ids(self, trace_ids: Sequence[str]) -> dict[str, str | None]:
        """取每条链路**最近一条**日志的 `request_id`（一次批量查询）。

        为什么"最近一条"而不是"任意一条"：`request_id` 在 `06 §3` 里
        标识**一次 HTTP 请求**，而一条 `trace_id` 可能被
        `X-Trace-ID` 复用在多个请求上（客户端显式传递时正是如此）。
        取最近一条让摘要指向"最近发生过的那次请求"，
        与 `last_seen_at` 的语义保持一致。
        """
        if not trace_ids:
            return {}
        parts = [
            self._trace_rows("access", AccessLog),
            self._trace_rows("audit", AuditLog),
            self._trace_rows("security", SecurityLog),
            self._trace_rows("operation", OperationLog),
            self._trace_rows("application", ApplicationLog),
        ]
        unioned = union_all(*parts).subquery()
        stmt = (
            select(unioned.c.trace_id, unioned.c.request_id)
            .where(unioned.c.trace_id.in_(trace_ids))
            .order_by(unioned.c.trace_id, unioned.c.created_at.desc())
            .distinct(unioned.c.trace_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {str(row.trace_id): row.request_id for row in rows}

    async def get_trace_entries(self, trace_id: str) -> list[dict[str, Any]]:
        """取某条链路上的全部日志条目（按时间升序）。

        返回 `dict` 而不是 ORM 对象：条目来自五张**不同**的表，
        用一个统一的 ORM 类型承载必然要假装它们同构。
        服务层负责把这些 dict 归一成 `TraceEntryResponse`。
        """
        entries: list[dict[str, Any]] = []
        # `Any` 而不是 `type[LogModel]`：联合类型的 `type[...]` 会让
        # mypy 把 `model` 收窄成 `type[Base]`（联合的公共基类），
        # 于是 `model.created_at` 变成 `attr-defined` 错误。
        # 每张表的列集合本就不同，这里的动态访问正是**有意为之**。
        tables: tuple[tuple[str, Any], ...] = (
            ("access", AccessLog),
            ("audit", AuditLog),
            ("security", SecurityLog),
            ("operation", OperationLog),
            ("application", ApplicationLog),
        )
        for name, model in tables:
            stmt = (
                select(model)
                .where(model.trace_id == trace_id)
                .order_by(model.created_at.asc(), model.id.asc())
                .limit(TRACE_ENTRY_LIMIT_PER_TABLE)
            )
            rows = (await self._session.execute(stmt)).scalars().unique().all()
            for row in rows:
                entries.append({"log_type": name, "row": row, "created_at": row.created_at})
        entries.sort(key=lambda item: (item["created_at"], str(item["log_type"])))
        return entries


__all__ = [
    "TRACE_ENTRY_LIMIT_PER_TABLE",
    "LogQueryRepository",
    "TraceSummary",
]
