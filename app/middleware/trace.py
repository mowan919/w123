"""Trace / Request ID 中间件。

Spec 06 §3 Trace：
    支持 X-Trace-ID 与 X-Request-ID；缺失时自动生成；
    必须贯穿 HTTP → Controller → Service → Repository → Audit/Security Log。

实现要点：
- 采用**纯 ASGI 中间件**而非 BaseHTTPMiddleware，确保 ContextVar 在
  请求任务内可靠传播（BaseHTTPMiddleware 在部分 Starlette 版本下会丢失上下文）；
- 请求头缺失时自动生成，并**回写响应头**，便于客户端与前端串联链路；
- 未捕获异常在此层转为统一 Envelope，保证 500 响应同样携带 trace/request id；
- 完整堆栈只写服务端日志，符合 Spec 10 §9（不得泄漏内部细节）。

日志说明：
本阶段输出的是"应用请求日志"基础形态；
Spec 06 §1 定义的五类日志表（Access/Security/Operation/Audit/Application）
属于 Phase 6 范围，本阶段不落库。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import (
    REQUEST_ID_HEADER,
    TRACE_ID_HEADER,
    new_request_id,
    new_trace_id,
    reset_ids,
    set_ids,
)
from app.core.error_codes import ErrorCode
from app.core.response import error_response

logger = logging.getLogger("app.request")

#: 客户端传入的 ID 长度上限，防止日志膨胀与响应头异常。
MAX_ID_LENGTH = 128


def _resolve_id(raw: str | None, generator: Callable[[], str]) -> str:
    """优先使用调用方传入的 ID，缺失或非法时自动生成。"""
    if raw:
        candidate = raw.strip()
        if candidate and len(candidate) <= MAX_ID_LENGTH:
            return candidate
        if candidate:
            logger.warning("忽略超长的 trace/request id，length=%s", len(candidate))
    return generator()


class TraceMiddleware:
    """为每个 HTTP 请求绑定 trace_id / request_id。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        trace_id = _resolve_id(headers.get(TRACE_ID_HEADER), new_trace_id)
        request_id = _resolve_id(headers.get(REQUEST_ID_HEADER), new_request_id)

        tokens = set_ids(trace_id, request_id)
        started = time.perf_counter()

        state: dict[str, Any] = {"response_started": False, "status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["response_started"] = True
                state["status"] = int(message.get("status", 500))
                raw_headers = list(message.get("headers") or [])
                raw_headers.append(
                    (TRACE_ID_HEADER.lower().encode("latin-1"), trace_id.encode("latin-1"))
                )
                raw_headers.append(
                    (REQUEST_ID_HEADER.lower().encode("latin-1"), request_id.encode("latin-1"))
                )
                message["headers"] = raw_headers
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                state["response_started"] = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            logger.exception(
                "unhandled_exception method=%s path=%s type=%s",
                scope.get("method"),
                scope.get("path"),
                type(exc).__name__,
            )
            if state["response_started"]:
                # 响应已开始发送，无法再写入信封，交给服务器关闭连接
                raise
            state["status"] = 500
            response = error_response(ErrorCode.INTERNAL_ERROR, http_status=500)
            await response(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "request_completed method=%s path=%s status=%s duration_ms=%s",
                scope.get("method"),
                scope.get("path"),
                state["status"],
                duration_ms,
            )
            reset_ids(tokens)
