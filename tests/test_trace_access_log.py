"""Trace 贯穿链路 + 访问日志落库（Spec `06 §1` / `06 §3`）。

两组证据
-------
1. **Trace**：`X-Trace-ID` / `X-Request-ID` 支持传入、缺失自动生成、
   回写响应头，并且真的写进了 `access_logs`（`06 §3` 要求的
   "HTTP → ... → Log 链路一致"，终点是日志本身，不是响应头）。
2. **Access Log**：每个请求都在 `access_logs` 留下 method / path / status /
   duration，且 `operator_id` 来自认证上下文而不是中间件自行解析令牌。

落库用真实会话（`flush_into_session`），因此这里验证的是端到端行为：
请求 → 缓冲 → 独立事务 → 数据库行。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI, Request
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import buffer as log_buffer
from app.core.context import set_actor_id
from app.core.response import success_response
from app.models.logs import AccessLog

pytestmark = pytest.mark.usefixtures("cleanup_generators")


@pytest.fixture
def flush_into_session(db_session: AsyncSession, isolate_log_flush: None) -> Iterator[None]:
    """让中间件的日志落库写入测试事务（用例结束随外层事务回滚）。

    依赖 `isolate_log_flush` 是为了强制顺序：那个 autouse 夹具先把提供者
    换成"吞掉写入"的替身，这里再覆盖成真实会话。若不声明依赖，
    顺序就取决于 pytest 的内部实现，而不是我们的意图。

    提供者**不关闭**会话 —— 它是用例自己的会话，
    落库结束就把夹具的会话关掉会让后续断言无处可查。
    """

    @asynccontextmanager
    async def provider() -> AsyncIterator[AsyncSession]:
        yield db_session

    log_buffer.set_session_provider(provider)
    try:
        yield
    finally:
        log_buffer.set_session_provider(None)


class TestTraceHeaders:
    async def test_provided_ids_are_echoed_back(
        self, client: AsyncClient, flush_into_session: None
    ) -> None:
        response = await client.get(
            "/health",
            headers={"X-Trace-ID": "trace-from-client", "X-Request-ID": "req-from-client"},
        )
        assert response.status_code == 200
        assert response.headers["X-Trace-ID"] == "trace-from-client"
        assert response.headers["X-Request-ID"] == "req-from-client"

    async def test_missing_ids_are_generated(
        self, client: AsyncClient, flush_into_session: None
    ) -> None:
        response = await client.get("/health")
        assert response.headers["X-Trace-ID"]
        assert response.headers["X-Request-ID"]
        assert len(response.headers["X-Trace-ID"]) == 32

    async def test_overlong_id_is_replaced(
        self, client: AsyncClient, flush_into_session: None
    ) -> None:
        response = await client.get("/health", headers={"X-Trace-ID": "x" * 500})
        assert len(response.headers["X-Trace-ID"]) == 32


class TestAccessLogIsWritten:
    async def test_not_found_request_is_logged(
        self, client: AsyncClient, db_session: AsyncSession, flush_into_session: None
    ) -> None:
        response = await client.get("/__trace_test__/missing", headers={"X-Trace-ID": "t-404"})
        assert response.status_code == 404

        rows = (
            (await db_session.execute(select(AccessLog).where(AccessLog.trace_id == "t-404")))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.method == "GET"
        assert row.path == "/__trace_test__/missing"
        assert row.status_code == 404
        assert row.duration_ms >= 0

    async def test_successful_request_is_logged(
        self, client: AsyncClient, db_session: AsyncSession, flush_into_session: None
    ) -> None:
        await client.get("/health", headers={"X-Trace-ID": "t-health"})

        rows = (
            (await db_session.execute(select(AccessLog).where(AccessLog.trace_id == "t-health")))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].status_code == 200

    async def test_query_string_is_not_stored(
        self, client: AsyncClient, db_session: AsyncSession, flush_into_session: None
    ) -> None:
        """凭据常出现在查询串里，30 天的访问日志不该替它们长期保存。"""
        await client.get("/health?token=super-secret-value", headers={"X-Trace-ID": "t-query"})

        rows = (
            (await db_session.execute(select(AccessLog).where(AccessLog.trace_id == "t-query")))
            .scalars()
            .all()
        )
        assert rows[0].path == "/health"
        assert "super-secret-value" not in rows[0].path

    async def test_user_agent_is_recorded(
        self, client: AsyncClient, db_session: AsyncSession, flush_into_session: None
    ) -> None:
        await client.get(
            "/health",
            headers={"X-Trace-ID": "t-ua", "User-Agent": "vctn-test-agent/1.0"},
        )
        rows = (
            (await db_session.execute(select(AccessLog).where(AccessLog.trace_id == "t-ua")))
            .scalars()
            .all()
        )
        assert rows[0].user_agent == "vctn-test-agent/1.0"

    async def test_request_id_is_recorded(
        self, client: AsyncClient, db_session: AsyncSession, flush_into_session: None
    ) -> None:
        await client.get("/health", headers={"X-Trace-ID": "t-req", "X-Request-ID": "req-42"})
        rows = (
            (await db_session.execute(select(AccessLog).where(AccessLog.trace_id == "t-req")))
            .scalars()
            .all()
        )
        assert rows[0].request_id == "req-42"

    async def test_unauthenticated_request_has_null_operator(
        self, client: AsyncClient, db_session: AsyncSession, flush_into_session: None
    ) -> None:
        await client.get("/health", headers={"X-Trace-ID": "t-anon"})
        rows = (
            (await db_session.execute(select(AccessLog).where(AccessLog.trace_id == "t-anon")))
            .scalars()
            .all()
        )
        assert rows[0].operator_id is None


class TestActorIdPropagation:
    """认证依赖写入上下文 → 中间件读出 → 落进 `access_logs`。

    这条链路的成立前提是**纯 ASGI 中间件**（见 `middleware/trace.py`）。
    若换成 `BaseHTTPMiddleware`，端点与中间件各自持有上下文副本，
    `operator_id` 会永远是 NULL —— 而测试会失败在这里，不会失败在线上。
    """

    async def test_actor_id_set_by_handler_reaches_access_log(
        self,
        app: FastAPI,
        temp_routes: FastAPI,
        client: AsyncClient,
        db_session: AsyncSession,
        flush_into_session: None,
    ) -> None:
        @app.get("/__trace_test__/actor")
        async def _actor_route() -> object:
            set_actor_id(424242)
            return success_response({"ok": True})

        await client.get("/__trace_test__/actor", headers={"X-Trace-ID": "t-actor"})

        rows = (
            (await db_session.execute(select(AccessLog).where(AccessLog.trace_id == "t-actor")))
            .scalars()
            .all()
        )
        assert rows[0].operator_id == 424242

    async def test_actor_id_does_not_leak_between_requests(
        self,
        app: FastAPI,
        temp_routes: FastAPI,
        client: AsyncClient,
        db_session: AsyncSession,
        flush_into_session: None,
    ) -> None:
        """中间件在请求入口把 actor 显式清零，身份不得跨请求残留。"""

        @app.get("/__trace_test__/actor-once")
        async def _actor_route(request: Request) -> object:
            if request.query_params.get("identify") == "1":
                set_actor_id(999001)
            return success_response({"ok": True})

        await client.get("/__trace_test__/actor-once?identify=1", headers={"X-Trace-ID": "t-a1"})
        await client.get("/__trace_test__/actor-once", headers={"X-Trace-ID": "t-a2"})

        rows = (
            (
                await db_session.execute(
                    select(AccessLog).where(AccessLog.trace_id.in_(["t-a1", "t-a2"]))
                )
            )
            .scalars()
            .all()
        )
        by_trace = {row.trace_id: row for row in rows}
        assert by_trace["t-a1"].operator_id == 999001
        assert by_trace["t-a2"].operator_id is None


class TestBufferIsBoundPerRequest:
    async def test_handler_can_record_audit_that_gets_persisted(
        self,
        app: FastAPI,
        temp_routes: FastAPI,
        client: AsyncClient,
        db_session: AsyncSession,
        flush_into_session: None,
    ) -> None:
        """服务层在请求内记录的事件，必须在**响应发出前**落库。

        这是"业务事务回滚也不丢审计"的端到端证据：
        端点在这里抛异常（业务事务回滚），但审计仍落库。
        """
        from app.audit.buffer import BufferingAuditRecorder
        from app.audit.events import AuditAction, AuditEvent
        from app.models.logs import AuditLog

        recorder = BufferingAuditRecorder()

        @app.get("/__trace_test__/audit-then-fail")
        async def _failing_route() -> object:
            recorder.record(
                AuditEvent.build(
                    action=AuditAction.USER_DELETE,
                    resource_type="USER",
                    resource_id=777,
                    operator_id=424242,
                    operator_username="tester",
                    trace_id="t-audit-fail",
                )
            )
            msg = "business failure"
            raise RuntimeError(msg)

        response = await client.get("/__trace_test__/audit-then-fail")

        assert response.status_code == 500
        rows = (
            (await db_session.execute(select(AuditLog).where(AuditLog.trace_id == "t-audit-fail")))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].action == "USER_DELETE"
        assert rows[0].result == "SUCCESS"

    async def test_error_response_still_carries_trace_headers(
        self, client: AsyncClient, flush_into_session: None
    ) -> None:
        response = await client.get("/health", headers={"X-Trace-ID": "t-ok"})
        assert response.headers["X-Trace-ID"] == "t-ok"

        missing = await client.get("/__trace_test__/missing", headers={"X-Trace-ID": "t-404-h"})
        assert missing.status_code == 404
        assert missing.headers["X-Trace-ID"] == "t-404-h"
