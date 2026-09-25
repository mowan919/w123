"""Trace / Request ID 中间件 + 访问日志落库（Spec `06 §1` / `06 §3`）。

Spec 06 §3 Trace：
    支持 X-Trace-ID 与 X-Request-ID；缺失时自动生成；
    必须贯穿 HTTP → Controller → Service → Repository → Audit/Security Log。

Spec 06 §1 Access Log：
    记录请求访问信息，保留 30 天。

实现要点：
- 采用**纯 ASGI 中间件**而非 BaseHTTPMiddleware，确保 ContextVar 在
  请求任务内可靠传播（BaseHTTPMiddleware 在部分 Starlette 版本下会丢失上下文）；
- 请求头缺失时自动生成，并**回写响应头**，便于客户端与前端串联链路；
- 未捕获异常在此层转为统一 Envelope，保证 500 响应同样携带 trace/request id；
- 完整堆栈只写服务端日志，符合 Spec 10 §9（不得泄漏内部细节）。

Phase 6 追加：请求级日志缓冲与落库时机
------------------------------------
本中间件是**每个 HTTP 请求唯一的日志落库点**：

```text
请求进入 → 绑定 trace/request id、绑定空 LogBuffer、actor_id = None
   │
   ├─ 认证依赖成功 → set_actor_id(user_id)
   ├─ 服务层 → self._audit.success/failure(...) → 只入缓冲，不碰数据库
   │
最终响应分片（more_body=false）**交还给服务器之前**
   ├─ 记录 access_logs（method / path / status / duration）
   ├─ logger.info("request_completed ...") → 进 application_logs
   └─ flush_logs()：用**独立事务**把全部缓冲一次落库
   │
最后才把该分片交给客户端
```

为什么锚点是"最后一个响应分片"而不是"函数返回后"
--------------------------------------------
放在 `finally`（函数返回后）实现更简单，但那一刻响应**已经**送达客户端，
于是存在一个窗口：客户端拿到 200，进程随即崩溃，而这次操作的审计还没落库。
`06 §2` / `10 §8` 要求关键操作可审计，最需要留证的恰恰就是那一次。

锚在最后一个分片则相反：**响应送达 ⇒ 日志已持久化**。
`finally` 里保留一次兜底调用 —— 若响应在中途异常终止（从未发出结尾分片），
仍有机会落库；`flush_logs()` 对空缓冲直接返回、不建立连接，兜底近乎零成本。

关于 `set_actor_id` 能否被本中间件看到
------------------------------------
能，但**仅因为这是纯 ASGI 中间件**。`ContextVar.set()` 作用于当前上下文，
而 Starlette 对 ASGI 应用不做上下文拷贝，端点与中间件共享同一个 context。
换用 `BaseHTTPMiddleware` 就会各自持有副本，actor_id 会永远读成 None ——
这是本项目坚持纯 ASGI 的第二个理由（第一个是 trace id 的可靠性）。

`path` 为什么不含 query
--------------------
查询串里常出现 `?token=` / `?code=` 这类一次性凭据，
把它写进保留 30 天的访问日志等于给凭据开了一条长期留存通道。
需要排查参数时以 trace/request id 关联应用日志，而不是把凭据存下来。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.audit.buffer import (
    LogBuffer,
    flush_logs,
    record_access,
    reset_buffer,
    set_buffer,
)
from app.audit.records import AccessRecord
from app.core.context import (
    REQUEST_ID_HEADER,
    TRACE_ID_HEADER,
    new_request_id,
    new_trace_id,
    reset_actor_id,
    reset_ids,
    set_actor_id,
    set_ids,
)
from app.core.error_codes import ErrorCode
from app.core.response import error_response

logger = logging.getLogger("app.request")

#: 客户端传入的 ID 长度上限，防止日志膨胀与响应头异常。
MAX_ID_LENGTH = 128

#: `access_logs.duration_ms` 是 `Integer`（int32）。
#:
#: 正常请求的耗时远小于此，但"上限保护"从来不是为正常情况准备的：
#: 一次被挂起的请求（客户端不读、后端等锁）足以让耗时突破 int32，
#: 那时插入会报错并**带走整批日志**。把耗时夹到列能表达的范围，
#: 好过让一条异常记录毁掉同批次的所有审计。
MAX_DURATION_MS = 2_147_483_647


def _resolve_id(raw: str | None, generator: Callable[[], str]) -> str:
    """优先使用调用方传入的 ID，缺失或非法时自动生成。"""
    if raw:
        candidate = raw.strip()
        if candidate and len(candidate) <= MAX_ID_LENGTH:
            return candidate
        if candidate:
            logger.warning("忽略超长的 trace/request id，length=%s", len(candidate))
    return generator()


def _client_ip(scope: Scope) -> str | None:
    """从 ASGI scope 取对端地址（与 `app/api/deps.py::client_ip` 同口径）。

    刻意不读 `X-Forwarded-For`：在受信代理配置冻结之前信任 XFF
    等于让任何客户端伪造来源 IP。
    """
    client = scope.get("client")
    if not client:
        return None
    host = client[0] if isinstance(client, (tuple, list)) and client else None
    return str(host) if host else None


class TraceMiddleware:
    """为每个 HTTP 请求绑定 trace_id / request_id，并统一落库请求级日志。"""

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
        buffer_token = set_buffer(LogBuffer())
        actor_token = set_actor_id(None)
        started = time.perf_counter()

        method = str(scope.get("method") or "")
        path = str(scope.get("path") or "")
        ip = _client_ip(scope)
        user_agent = headers.get("User-Agent")

        state: dict[str, Any] = {"response_started": False, "status": 500, "logged": False}

        async def finish() -> None:
            """记录访问日志并落库（幂等，且**绝不向调用方抛异常**）。"""
            if state["logged"]:
                return
            state["logged"] = True
            try:
                duration_ms = min(
                    MAX_DURATION_MS,
                    max(0, round((time.perf_counter() - started) * 1000)),
                )
                record_access(
                    AccessRecord.build(
                        method=method,
                        path=path,
                        status_code=int(state["status"]),
                        duration_ms=duration_ms,
                        ip=ip,
                        user_agent=user_agent,
                    )
                )
                logger.info(
                    "request_completed method=%s path=%s status=%s duration_ms=%s",
                    method,
                    path,
                    state["status"],
                    duration_ms,
                )
                # `flush_logs` 自身不抛异常（失败只计数 + 记 ERROR）。
                await flush_logs()
            except Exception:
                logger.exception("请求级日志处理失败 path=%s", path)

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
                # 关键顺序：**先落库，再把最后一个分片交给服务器**。
                await finish()
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            logger.exception(
                "unhandled_exception method=%s path=%s type=%s",
                method,
                path,
                type(exc).__name__,
            )
            if state["response_started"]:
                # 响应已开始发送，无法再写入信封，交给服务器关闭连接
                raise
            state["status"] = 500
            response = error_response(ErrorCode.INTERNAL_ERROR, http_status=500)
            await response(scope, receive, send_wrapper)
        finally:
            # 兜底：响应若从未发出结尾分片（连接中断 / 流式异常），
            # 在这里仍有落库机会。缓冲区为空时 `flush_logs` 不建立连接。
            await finish()
            reset_actor_id(actor_token)
            reset_buffer(buffer_token)
            reset_ids(tokens)
