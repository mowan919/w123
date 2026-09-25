"""日志链路：缓冲 → 落库 → 失败可见（不依赖数据库）。

为什么请求级日志要经过缓冲，而不是"边发生边写"
--------------------------------------------
见 `app/audit/buffer.py` 的模块文档。本模块把该设计的**每一处承诺**
变成断言：

1. 记录动作不碰数据库（服务层可以放心地在业务事务里记录拒绝事件）；
2. `flush_logs()` 用独立会话落库，因此业务事务回滚不影响日志；
3. `drain()` 幂等 —— "中间件落库一次 + 兜底再落库一次"不产生重复行；
4. 落库失败**不阻断**请求，但必须**响亮**（计数 + ERROR）。

第 2 条是本模块的重点：它是"越权被拒也有审计"这句话的技术依据。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.audit import buffer as log_buffer
from app.audit.buffer import (
    BufferingAuditRecorder,
    FlushResult,
    activated_buffer,
    current_buffer,
    drain,
    flush_logs,
    record_access,
    record_application,
    record_audit,
)
from app.audit.events import AuditAction, AuditEvent
from app.audit.records import AccessRecord, ApplicationRecord
from app.core.logging import DB_LOG_LEVEL, DbLogHandler, configure_logging


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    """还原 root logger 的 handler 与级别。

    `configure_logging(force=True)` 会**清空** root 的 handler ——
    其中包含 pytest 自己挂上去的日志捕获 handler。
    不还原的话，后续用例的 `caplog` 会静默失效（表现为"抓不到日志"），
    那是一个与用例本身无关、却极难定位的失败。
    """
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    try:
        yield
    finally:
        for handler in list(root.handlers):
            if handler not in original_handlers:
                root.removeHandler(handler)
        for handler in original_handlers:
            if handler not in root.handlers:
                root.addHandler(handler)
        root.setLevel(original_level)


def _event(action: AuditAction = AuditAction.USER_CREATE) -> AuditEvent:
    return AuditEvent.build(
        action=action,
        resource_type="USER",
        resource_id=1,
        operator_id=1,
        operator_username="tester",
    )


class _RecordingSession:
    """记录被写入的批次的会话替身（不连数据库）。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self._fail = fail

    async def execute(self, statement: Any, params: Any = None) -> None:
        if self._fail:
            msg = "simulated database outage"
            raise RuntimeError(msg)
        self.calls.append((statement, params))

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        return None


def _provider(session: Any) -> Any:
    @asynccontextmanager
    async def provider() -> AsyncIterator[Any]:
        try:
            yield session
        finally:
            await session.close()

    return provider


class TestBufferContext:
    def test_no_active_buffer_outside_a_request(self) -> None:
        assert current_buffer() is None

    async def test_activated_buffer_binds_and_resets(self) -> None:
        async with activated_buffer() as buffer:
            assert current_buffer() is buffer
            record_audit(_event())
            assert len(buffer.audits) == 1
        assert current_buffer() is None

    async def test_records_go_to_the_active_buffer(self) -> None:
        drain()  # 清掉兜底缓冲的残留
        async with activated_buffer() as buffer:
            record_access(AccessRecord(method="GET", path="/x", status_code=200, duration_ms=1))
            record_application(ApplicationRecord(level="INFO", logger="app.test", message="hello"))
        assert len(buffer.accesses) == 1
        assert len(buffer.applications) == 1

    def test_records_outside_a_request_go_to_the_fallback_buffer(self) -> None:
        """启动期 / 非 HTTP 入口的日志不得被静默丢弃。"""
        drain()
        record_audit(_event())
        assert len(drain().audits) == 1

    def test_buffering_recorder_implements_the_port(self) -> None:
        drain()
        BufferingAuditRecorder().record(_event(AuditAction.AUTH_LOGIN_FAILURE))
        drained = drain()
        assert [str(e.action) for e in drained.audits] == ["AUTH_LOGIN_FAILURE"]


class TestDrainIsIdempotent:
    def test_second_drain_is_empty(self) -> None:
        drain()
        record_audit(_event())
        assert len(drain().audits) == 1
        assert drain().is_empty()

    async def test_request_buffer_and_fallback_are_merged_once(self) -> None:
        drain()
        record_audit(_event(AuditAction.DEPARTMENT_READ))  # 兜底缓冲
        async with activated_buffer() as active:
            record_audit(_event(AuditAction.USER_READ))
            record_audit(_event(AuditAction.ROLE_READ))
            merged = drain()
            assert len(merged.audits) == 3
            # 兜底在前（时间上更早），使同批次内的行序与真实发生顺序一致
            assert str(merged.audits[0].action) == "DEPARTMENT_READ"
            # 取出后即清空，重复 drain 不再产生行
            assert drain().is_empty()
            assert active.audits == []


class TestAuditPayloadsAreScrubbedBeforeBuffering:
    def test_password_in_before_data_is_redacted(self) -> None:
        drain()
        event = AuditEvent.build(
            action=AuditAction.USER_UPDATE,
            resource_type="USER",
            resource_id=1,
            operator_id=1,
            operator_username="t",
            before_data={"password": "plaintext", "phone": "13812341234"},
        )
        record_audit(event)
        stored = drain().audits[0]
        assert stored.before_data == {"password": "<redacted>", "phone": "138****1234"}

    def test_empty_payload_stays_none(self) -> None:
        drain()
        record_audit(_event())
        assert drain().audits[0].before_data is None

    def test_original_event_is_not_mutated(self) -> None:
        drain()
        event = AuditEvent.build(
            action=AuditAction.USER_UPDATE,
            resource_type="USER",
            resource_id=1,
            operator_id=1,
            operator_username="t",
            before_data={"password": "plaintext"},
        )
        record_audit(event)
        drain()
        assert event.before_data == {"password": "plaintext"}


class TestFlush:
    async def test_empty_buffer_does_not_open_a_session(self) -> None:
        drain()
        session = _RecordingSession()
        log_buffer.set_session_provider(_provider(session))
        result = await flush_logs()
        assert result == FlushResult()
        assert session.calls == []
        assert session.commits == 0

    async def test_flush_uses_its_own_session_and_commits(self) -> None:
        drain()
        session = _RecordingSession()
        log_buffer.set_session_provider(_provider(session))
        record_audit(_event(AuditAction.USER_CREATE))
        record_access(AccessRecord(method="GET", path="/x", status_code=200, duration_ms=1))

        result = await flush_logs()

        assert result.audit == 1
        assert result.access == 1
        assert session.commits == 1
        assert log_buffer.flush_failures == 0

    async def test_flush_clears_the_buffer(self) -> None:
        drain()
        session = _RecordingSession()
        log_buffer.set_session_provider(_provider(session))
        record_audit(_event())
        await flush_logs()
        assert (await flush_logs()).total == 0

    async def test_database_failure_does_not_raise_and_is_counted(self) -> None:
        """日志设施故障不得让业务请求失败，但必须**响亮**。"""
        drain()
        log_buffer.flush_failures = 0
        log_buffer.set_session_provider(_provider(_RecordingSession(fail=True)))
        record_audit(_event())

        result = await flush_logs()

        assert result.total == 0
        assert log_buffer.flush_failures == 1

    async def test_failure_keeps_the_invariant_of_never_raising(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        drain()
        log_buffer.set_session_provider(_provider(_RecordingSession(fail=True)))
        record_audit(_event())
        with caplog.at_level(logging.ERROR, logger="app.audit.buffer"):
            await flush_logs()
        assert "日志落库失败" in caplog.text

    async def test_partial_failure_rolls_back_nothing_silently(self) -> None:
        """一次 flush 成败是二元的：要么整批写入并提交，要么整批不写。

        这里断言的是**可观察行为**：失败时既不提交、也不把缓冲留成半截
        （缓冲已被 drain 清空，不会在下次 flush 时产生"重复一半"的行）。
        """
        drain()
        session = _RecordingSession(fail=True)
        log_buffer.set_session_provider(_provider(session))
        record_audit(_event())
        await flush_logs()
        assert session.commits == 0
        assert drain().is_empty()


class _HangingSession:
    """永不返回的会话 —— 模拟数据库主机"不响应"（丢包而非拒绝连接）。"""

    async def execute(self, statement: Any, params: Any = None) -> None:
        await asyncio.sleep(3600)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


class TestFlushIsBoundedInTime:
    """落库不得把请求挂住 —— `/health` 是存活探针，挂住它等于服务不可用。"""

    async def test_hanging_database_is_abandoned_after_the_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        drain()
        log_buffer.set_session_provider(_provider(_HangingSession()))
        monkeypatch.setattr(log_buffer, "FLUSH_TIMEOUT_SECONDS", 0.05)
        record_audit(_event())

        result = await flush_logs()

        assert result.total == 0
        assert log_buffer.flush_failures == 1

    async def test_timeout_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        drain()
        log_buffer.set_session_provider(_provider(_HangingSession()))
        monkeypatch.setattr(log_buffer, "FLUSH_TIMEOUT_SECONDS", 0.05)
        record_audit(_event())
        await flush_logs()  # 不抛异常即可


class TestCircuitBreaker:
    """连续失败后停止尝试 —— 否则数据库下线期间每个请求都要付一次连接尝试。"""

    async def test_circuit_opens_after_threshold_failures(self) -> None:
        log_buffer.reset_circuit()
        log_buffer.set_session_provider(_provider(_RecordingSession(fail=True)))
        for _ in range(log_buffer.CIRCUIT_FAILURE_THRESHOLD):
            drain()
            record_audit(_event())
            await flush_logs()

        assert log_buffer.circuit_is_open() is True

    async def test_open_circuit_skips_the_database_and_drops(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        drain()
        session = _RecordingSession()
        log_buffer.set_session_provider(_provider(session))
        monkeypatch.setattr(log_buffer, "_circuit_open_until", float("inf"))

        record_audit(_event())
        result = await flush_logs()

        assert result.total == 0
        assert session.calls == []  # 完全没有访问数据库
        assert log_buffer.dropped_logs >= 1

    async def test_success_closes_the_circuit(self) -> None:
        log_buffer.reset_circuit()
        log_buffer._circuit_open_until = 0.0
        log_buffer._consecutive_failures = 2
        log_buffer.set_session_provider(_provider(_RecordingSession()))
        record_audit(_event())
        await flush_logs()
        assert log_buffer.circuit_is_open() is False
        assert log_buffer._consecutive_failures == 0

    async def test_circuit_can_be_reset(self) -> None:
        log_buffer._circuit_open_until = float("inf")
        log_buffer.reset_circuit()
        assert log_buffer.circuit_is_open() is False


class TestDbLogHandler:
    def test_emit_buffers_an_application_record(self) -> None:
        drain()
        handler = DbLogHandler()
        record = logging.LogRecord(
            name="app.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        handler.emit(record)
        drained = drain()
        assert len(drained.applications) == 1
        assert drained.applications[0].message == "hello world"
        assert drained.applications[0].logger == "app.test"

    def test_emit_skips_while_flushing(self) -> None:
        """切断"落库失败 → 记 ERROR → 又被收进缓冲"的增长回路。"""
        drain()
        token = log_buffer._flushing.set(True)
        try:
            DbLogHandler().emit(
                logging.LogRecord(
                    name="app.test",
                    level=logging.ERROR,
                    pathname=__file__,
                    lineno=1,
                    msg="should be dropped",
                    args=(),
                    exc_info=None,
                )
            )
        finally:
            log_buffer._flushing.reset(token)
        assert drain().is_empty()

    def test_broken_format_does_not_raise(self) -> None:
        drain()
        handler = DbLogHandler()
        record = logging.LogRecord(
            name="app.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="%s %s",
            args=("only-one",),
            exc_info=None,
        )
        handler.emit(record)  # 不抛异常即可


@pytest.mark.usefixtures("restore_root_logger")
class TestConfigureLoggingWiring:
    """`configure_logging` 的挂载 / 幂等 / 摘除。"""

    def test_db_handler_is_attached_when_enabled(self) -> None:
        configure_logging("INFO", json_output=True, db_output=True, force=True)
        root = logging.getLogger()
        handlers = [h for h in root.handlers if isinstance(h, DbLogHandler)]
        assert len(handlers) == 1
        assert handlers[0].level == DB_LOG_LEVEL

    def test_db_handler_is_idempotent(self) -> None:
        configure_logging("INFO", json_output=True, db_output=True, force=True)
        configure_logging("INFO", json_output=True, db_output=True, force=False)
        root = logging.getLogger()
        assert len([h for h in root.handlers if isinstance(h, DbLogHandler)]) == 1

    def test_db_handler_can_be_detached(self) -> None:
        configure_logging("INFO", json_output=True, db_output=True, force=True)
        configure_logging("INFO", json_output=True, db_output=False, force=False)
        root = logging.getLogger()
        assert [h for h in root.handlers if isinstance(h, DbLogHandler)] == []

    def test_stream_handler_still_present(self) -> None:
        configure_logging("INFO", json_output=True, db_output=False, force=True)
        assert isinstance(logging.getLogger().handlers[0], logging.StreamHandler)


class TestSessionProvider:
    def test_provider_can_be_restored_to_default(self) -> None:
        log_buffer.set_session_provider(_provider(_RecordingSession()))
        log_buffer.set_session_provider(None)
        assert log_buffer._session_provider is None
