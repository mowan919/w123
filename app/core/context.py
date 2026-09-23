"""Trace / Request ID 上下文。

Spec 06 §3 Trace：支持 X-Trace-ID 与 X-Request-ID，缺失时自动生成；
必须能够贯穿 HTTP → Controller → Service → Repository → Audit/Security Log。

实现说明：
- 使用 ContextVar 保存当前请求的 trace_id / request_id，保证在 async 任务内可见；
- 由 `app.middleware.trace.TraceMiddleware` 在请求入口设置、在请求结束时复位；
- 日志 Formatter 从本模块读取，从而实现全链路携带。

注意：
- 这里生成的 ID 是**链路追踪标识字符串**，不是业务主键。
  Spec 00 §6 / 07 §2 明确禁止使用 UUID 作为业务主键；本模块不涉及业务主键。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

TRACE_ID_HEADER = "X-Trace-ID"
REQUEST_ID_HEADER = "X-Request-ID"

_trace_id_var: ContextVar[str | None] = ContextVar("vctn_trace_id", default=None)
_request_id_var: ContextVar[str | None] = ContextVar("vctn_request_id", default=None)


def new_trace_id() -> str:
    """生成新的 trace id（32 位十六进制）。"""
    return uuid.uuid4().hex


def new_request_id() -> str:
    """生成新的 request id（32 位十六进制）。"""
    return uuid.uuid4().hex


def get_trace_id() -> str | None:
    """返回当前上下文的 trace id；不在请求上下文中时为 None。"""
    return _trace_id_var.get()


def get_request_id() -> str | None:
    """返回当前上下文的 request id；不在请求上下文中时为 None。"""
    return _request_id_var.get()


def set_ids(trace_id: str, request_id: str) -> tuple[Token[str | None], Token[str | None]]:
    """设置当前上下文的 trace/request id，返回用于复位的 token。"""
    return _trace_id_var.set(trace_id), _request_id_var.set(request_id)


def reset_ids(tokens: tuple[Token[str | None], Token[str | None]]) -> None:
    """复位 trace/request id 上下文。"""
    trace_token, request_token = tokens
    _trace_id_var.reset(trace_token)
    _request_id_var.reset(request_token)


@contextmanager
def trace_context(trace_id: str, request_id: str) -> Iterator[None]:
    """以上下文管理器方式绑定 trace/request id（供非 HTTP 场景复用）。"""
    tokens = set_ids(trace_id, request_id)
    try:
        yield
    finally:
        reset_ids(tokens)
