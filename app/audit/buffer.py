"""请求作用域的日志缓冲与落库（Phase 6 的核心机制）。

为什么是"缓冲 + 统一落库"而不是"边发生边写"
-----------------------------------------
审计有一条硬性义务：**拒绝也必须留痕**（`10 §8`，Phase 2 起由
`AuditGuard.denial_audited` 保证）。而拒绝的实现方式是**抛异常**，
抛异常意味着端点的 `session.commit()` 不会执行 —— 业务事务回滚。

若审计与业务共用同一个事务，那么"越权被拒"这件事**恰好会被回滚掉**，
留下的只有成功记录。也就是说，最需要审计的事件反而没有审计。
这不是理论问题：`denial_audited` 的整个存在意义就是让拒绝可见。

因此本模块把日志与业务事务**彻底分离**：

```text
业务请求 ──→ 服务层 self._audit.success/failure(...)
                    │  （只入内存缓冲，不碰数据库）
                    ▼
             LogBuffer（请求作用域，ContextVar）
                    │
        响应即将发出时，由中间件用**独立事务**一次性落库
                    ▼
       audit_logs / security_logs / operation_logs / access_logs / application_logs
```

这样无论业务事务是提交还是回滚，日志都已落库。

为什么在**响应发出之前**落库（而不是之后）
---------------------------------------
"响应已到达客户端" ⇒ "本次请求的审计已持久化"。这个蕴含关系是刻意建立的：
反过来做（先发响应再落库）会在两者之间留下一个窗口，
进程在该窗口内崩溃就会丢掉"刚刚答复过的那次操作"的记录 ——
而那正是最需要留证的时刻。代价是每个请求多一次数据库往返（已登记为 INTERIM）。

落库失败怎么办
------------
**不阻断业务响应**（与 `app/db/session.py` 的 fail-soft 取向一致）：
日志设施故障不应让管理功能整体不可用。但失败必须**响亮**：
记为 ERROR 并递增 `flush_failures` 计数，使"日志没写进去"这件事可被监控发现，
而不是安静地丢失。

`drain()` 是幂等的：缓冲区被取走后即清空，
因此"中间件落库一次 + 兜底再落库一次"不会产生重复行。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
)
from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.events import AuditEvent
from app.audit.records import AccessRecord, ApplicationRecord
from app.core.masking import scrub

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LogBuffer:
    """一次请求（或一个兜底批次）内累积的待落库日志。"""

    audits: list[AuditEvent] = field(default_factory=list)
    accesses: list[AccessRecord] = field(default_factory=list)
    applications: list[ApplicationRecord] = field(default_factory=list)

    def is_empty(self) -> bool:
        """是否没有任何待落库内容。"""
        return not (self.audits or self.accesses or self.applications)

    def add_audit(self, event: AuditEvent) -> None:
        """加入一条审计事件（**落库前完成脱敏**，`06 §4`）。"""
        self.audits.append(_scrub_event(event))

    def add_access(self, record: AccessRecord) -> None:
        """加入一条访问日志。"""
        self.accesses.append(record)

    def add_application(self, record: ApplicationRecord) -> None:
        """加入一条应用日志（正文已由 `MaskingFilter` 脱敏）。"""
        self.applications.append(record)


def _scrub_event(event: AuditEvent) -> AuditEvent:
    """对审计事件的 `before_data` / `after_data` 做递归脱敏。

    为什么在**写入缓冲时**就脱敏，而不是在 SQL 之前：
    `JSONB` 一旦写入就无法"事后补救"，而缓冲到落库之间还隔着一次
    `drain()`。把脱敏放在最靠近产生点的一侧，使"未脱敏数据"
    在内存中停留的时间最短，也让"有没有漏脱敏"只取决于一处代码。
    """
    return replace(
        event,
        before_data=_scrub_payload(event.before_data),
        after_data=_scrub_payload(event.after_data),
    )


def _scrub_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """脱敏一个 JSONB 载荷；空载荷保持为 `None`（不写空对象）。"""
    if not payload:
        return None
    return cast("dict[str, Any]", scrub(payload))


# ---------------------------------------------------------------------------
# 上下文
# ---------------------------------------------------------------------------
_buffer_var: ContextVar[LogBuffer | None] = ContextVar("vctn_log_buffer", default=None)

#: 无请求上下文时的兜底缓冲。
#:
#: 覆盖两种情形：① 应用启动 / 关闭期间的日志（此时还没有任何请求）；
#: ② 直接调用服务层的测试与非 HTTP 入口。
#: 没有它的话，这些日志会被**静默丢弃** —— 而"静默"正是本项目一贯拒绝的模式。
_pending = LogBuffer()


def current_buffer() -> LogBuffer | None:
    """返回当前上下文的缓冲区；不在请求上下文中时为 None。"""
    return _buffer_var.get()


def set_buffer(buffer: LogBuffer) -> Token[LogBuffer | None]:
    """绑定当前上下文的缓冲区，返回用于复位的 token。"""
    return _buffer_var.set(buffer)


def reset_buffer(token: Token[LogBuffer | None]) -> None:
    """复位缓冲区上下文。"""
    _buffer_var.reset(token)


def _target() -> LogBuffer:
    """选择写入目标：请求缓冲区优先，否则兜底缓冲区。"""
    active = _buffer_var.get()
    return active if active is not None else _pending


def record_audit(event: AuditEvent) -> None:
    """记录一条审计事件（写入当前请求缓冲，或兜底缓冲）。"""
    _target().add_audit(event)


def record_access(record: AccessRecord) -> None:
    """记录一条访问日志。"""
    _target().add_access(record)


def record_application(record: ApplicationRecord) -> None:
    """记录一条应用日志。"""
    _target().add_application(record)


def drain() -> LogBuffer:
    """取出并清空待写内容。

    请求缓冲区与兜底缓冲区**合并**返回：一次请求的落库顺便把
    启动期间积压的兜底日志一并写入，避免它们永远等不到自己的请求。
    合并顺序是"兜底在前"（兜底内容在时间上更早），
    使同一批次内的行序与真实发生顺序一致。
    """
    merged = LogBuffer()
    active = _buffer_var.get()
    sources: list[LogBuffer] = [_pending]
    if active is not None and active is not _pending:
        sources.append(active)
    for source in sources:
        merged.audits.extend(source.audits)
        merged.accesses.extend(source.accesses)
        merged.applications.extend(source.applications)
        source.audits.clear()
        source.accesses.clear()
        source.applications.clear()
    return merged


# ---------------------------------------------------------------------------
# 端口实现
# ---------------------------------------------------------------------------
class BufferingAuditRecorder:
    """`AuditRecorder` 端口的缓冲实现（服务层唯一感知的日志接口）。

    刻意保持 `record()` **同步**：它是 `AuditRecorder` 的既有契约，
    已被 Phase 2~5 的全部服务层调用点使用。改成异步会波及每一个
    `self._audit.success(...)`，而收益仅是"省一次缓冲" ——
    真正需要独立事务的是**落库**那一刻，不是记录那一刻。
    """

    __slots__ = ()

    def record(self, event: AuditEvent) -> None:
        record_audit(event)


@asynccontextmanager
async def activated_buffer() -> AsyncIterator[LogBuffer]:
    """在上下文中绑定一个新的缓冲区，退出时复位。"""
    buffer = LogBuffer()
    token = set_buffer(buffer)
    try:
        yield buffer
    finally:
        reset_buffer(token)


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------
#: 会话工厂提供者签名。默认开一个**独立会话**；测试可替换为受控会话，
#: 使落库行落在测试事务内从而可被断言。
SessionProvider = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_session_provider: SessionProvider | None = None

#: 落库失败计数（供监控与测试观察）。
flush_failures = 0

#: 因熔断打开而被**主动丢弃**的日志条数。
#:
#: 丢弃是失败路径的一部分（见 `_drop`）：数据库长时间不可用时，
#: 继续把日志攒在内存里只会把进程拖垮。但"丢了多少"必须可观测，
#: 否则就变成了静默丢失 —— 那正是本项目一贯拒绝的模式。
dropped_logs = 0

#: 单次落库的时间上限（秒）。
#:
#: 为什么必须有上限：`asyncio` 下 asyncpg 的连接超时默认是 60 秒。
#: 若数据库主机"不响应"（丢包而非拒绝连接），一次落库就能挂住请求 60 秒。
#: 而 `/health` 是**存活探针** —— 挂住它会让编排系统判定进程已死并重启，
#: 于是"数据库抖动"被放大成"整个服务不可用"。上限把这条路径钉在秒级。
FLUSH_TIMEOUT_SECONDS = 5.0

#: 连续失败达到该次数后打开熔断。
CIRCUIT_FAILURE_THRESHOLD = 3

#: 熔断保持打开的秒数。到期后放行一次尝试（半开），成功则闭合。
CIRCUIT_COOLDOWN_SECONDS = 60.0

_consecutive_failures = 0
_circuit_open_until = 0.0
_circuit_notified = False

#: 是否正处于落库过程中。
#:
#: 存在的唯一理由是**切断一条反馈回路**：落库失败会记 ERROR，
#: 而 ERROR 又会被 `DbLogHandler` 收进缓冲 —— 若数据库持续不可用，
#: 每次 flush 都产生"下一次要写的日志"，缓冲与失败计数无限增长。
#: 落库期间的日志因此直接丢弃（它们描述的是日志设施自身的问题，
#: 已由 `flush_failures` 计数与 stderr 上的原始 handler 表达）。
_flushing: ContextVar[bool] = ContextVar("vctn_flushing", default=False)


def is_flushing() -> bool:
    """当前是否处于日志落库过程中（供 `DbLogHandler` 判断是否投递）。"""
    return _flushing.get()


def circuit_is_open() -> bool:
    """落库熔断是否处于打开状态。"""
    return time.monotonic() < _circuit_open_until


def reset_circuit() -> None:
    """闭合熔断并清零失败计数（测试与运维恢复用）。"""
    global _consecutive_failures, _circuit_open_until, _circuit_notified
    _consecutive_failures = 0
    _circuit_open_until = 0.0
    _circuit_notified = False


def _drop(buffer: LogBuffer) -> None:
    """丢弃一批无法落库的日志并计数（熔断打开期间）。"""
    global dropped_logs, _circuit_notified
    count = len(buffer.audits) + len(buffer.accesses) + len(buffer.applications)
    dropped_logs += count
    if not _circuit_notified:
        _circuit_notified = True
        logger.error(
            "日志落库熔断已打开（连续失败 %d 次），期间产生的日志将被丢弃，"
            "dropped_batch=%d；%.0f 秒后重试",
            _consecutive_failures,
            count,
            CIRCUIT_COOLDOWN_SECONDS,
        )


def _on_success() -> None:
    """落库成功：闭合熔断。"""
    global _consecutive_failures, _circuit_open_until, _circuit_notified
    _consecutive_failures = 0
    _circuit_open_until = 0.0
    _circuit_notified = False


def _on_failure(buffer: LogBuffer, exc: BaseException) -> None:
    """落库失败：计数，并在连续失败达到阈值后打开熔断。"""
    global flush_failures, dropped_logs, _consecutive_failures, _circuit_open_until
    flush_failures += 1
    dropped_logs += len(buffer.audits) + len(buffer.accesses) + len(buffer.applications)
    _consecutive_failures += 1
    if _consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
        _circuit_open_until = time.monotonic() + CIRCUIT_COOLDOWN_SECONDS
    logger.error(
        "日志落库失败（连续第 %d 次）audits=%d accesses=%d applications=%d error=%s",
        _consecutive_failures,
        len(buffer.audits),
        len(buffer.accesses),
        len(buffer.applications),
        type(exc).__name__,
        exc_info=exc,
    )


def set_session_provider(provider: SessionProvider | None) -> None:
    """替换落库用的会话提供者（`None` 表示恢复默认）。

    做成可替换的不是为了"方便测试"，而是因为落库必须使用
    **与业务无关的独立会话**：如果它复用业务会话，回滚时日志一起消失 ——
    那正是本模块要避免的事。既然必须外开，就必须能注入。
    """
    global _session_provider
    _session_provider = provider


@asynccontextmanager
async def _default_session_provider() -> AsyncIterator[AsyncSession]:
    """默认提供者：从进程级工厂取一个独立会话。"""
    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        yield session


@dataclass(frozen=True, slots=True)
class FlushResult:
    """一次落库的结果（各类别写入行数）。"""

    audit: int = 0
    security: int = 0
    operation: int = 0
    access: int = 0
    application: int = 0

    @property
    def total(self) -> int:
        """写入总行数。"""
        return self.audit + self.security + self.operation + self.access + self.application


async def flush_logs() -> FlushResult:
    """把缓冲中的日志用独立事务落库。

    Returns:
        各类别写入行数；无待写内容时返回全 0（不建立数据库连接）。

    Note:
        **不抛异常，也不阻塞请求**。日志设施故障不得让管理功能不可用，
        因此这里有三层保护：

        1. 整体超时 `FLUSH_TIMEOUT_SECONDS` —— 数据库"不响应"时
           也不会把请求挂到 asyncpg 的默认 60 秒连接超时；
        2. 连续失败 `CIRCUIT_FAILURE_THRESHOLD` 次后熔断
           `CIRCUIT_COOLDOWN_SECONDS` 秒，期间直接丢弃缓冲，
           不再为每个请求付一次连接尝试；
        3. 丢弃量计入 `dropped_logs`，失败计入 `flush_failures`，
           使"日志没写进去"可被监控发现，而不是安静地消失。
    """
    # 延迟导入：`app.repositories.logs` 在**顶层**导入本模块的
    # `LogBuffer` / `FlushResult`（它们是其接口的一部分）。
    # 若此处也写成顶层导入，两个模块就互相依赖。
    # 方向是刻意的：仓储依赖缓冲的值对象，落库动作依赖仓储。
    from app.repositories.logs import LogRepository

    buffer = drain()
    if buffer.is_empty():
        return FlushResult()

    if circuit_is_open():
        _drop(buffer)
        return FlushResult()

    provider = _session_provider or _default_session_provider
    token = _flushing.set(True)
    try:
        async with asyncio.timeout(FLUSH_TIMEOUT_SECONDS):
            async with provider() as session:
                result = await LogRepository(session).append_buffer(buffer)
                await session.commit()
    except Exception as exc:
        _on_failure(buffer, exc)
        return FlushResult()
    else:
        _on_success()
        return result
    finally:
        _flushing.reset(token)


__all__ = [
    "CIRCUIT_COOLDOWN_SECONDS",
    "CIRCUIT_FAILURE_THRESHOLD",
    "FLUSH_TIMEOUT_SECONDS",
    "BufferingAuditRecorder",
    "FlushResult",
    "LogBuffer",
    "activated_buffer",
    "circuit_is_open",
    "current_buffer",
    "drain",
    "dropped_logs",
    "flush_failures",
    "flush_logs",
    "is_flushing",
    "record_access",
    "record_application",
    "record_audit",
    "reset_buffer",
    "reset_circuit",
    "set_buffer",
    "set_session_provider",
]
