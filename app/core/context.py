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

Phase 6 追加：`actor_id`
----------------------
Access Log（`06 §1`）需要记录"这次请求是谁发的"。
认证依赖（`app/api/deps.py::get_current_actor`）在解析出操作者后把 ID 写入本上下文，
中间件在请求结束时读出并写入 `access_logs.operator_id`。

为什么经 ContextVar 而不是让中间件自己解析令牌：
中间件再次解析令牌等于把认证逻辑变成两份实现，而"哪一份说了算"没有答案。
未认证请求（登录、健康检查、404）此值为 `None`，与 `access_logs.operator_id`
可空的语义一致。
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
_actor_id_var: ContextVar[int | None] = ContextVar("vctn_actor_id", default=None)


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


def get_actor_id() -> int | None:
    """返回当前上下文已认证用户 ID；未认证或不在请求上下文时为 None。"""
    return _actor_id_var.get()


def set_actor_id(actor_id: int | None) -> Token[int | None]:
    """记录当前请求的操作者 ID，返回用于复位的 token。

    接受 `None` 是为了让中间件在请求入口**显式清零**：
    如果只依赖"上下文本来就是新的"，那么任何一次未走到复位的提前返回，
    都会把上一个请求的身份带到下一个请求上 —— 那将是一条
    "访问日志把 A 的操作记成 B"的静默错误。显式清零让不变量成立，
    而不是让不变量依赖运行时的上下文创建策略。
    """
    return _actor_id_var.set(actor_id)


def reset_actor_id(token: Token[int | None]) -> None:
    """复位操作者上下文。"""
    _actor_id_var.reset(token)


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
