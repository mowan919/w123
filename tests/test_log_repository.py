"""五类日志落库（Spec `06 §1` / `06 §2` / `10 §8`）。

需要真实 PostgreSQL（`db_session` 夹具，外层事务回滚）。
本模块验证的是**一批事件如何分发到五张表**，以及几处只有数据库才能验证的
不变量：字段齐全、超长值被截断、append-only 触发器真的拒绝改写。

断言为什么统一按 `trace_id` 过滤
------------------------------
`db_session` 走的是 `.env` 里的真实库。表里可能已经存在**已提交**的历史行
（例如有人用真实进程跑过一次），无过滤的 `select(AuditLog).all()` 会读到它们，
让"写入了 3 行"这类断言变成环境依赖。因此每个用例用一个唯一的 trace 标记，
只断言自己写入的那一组。
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.buffer import FlushResult, LogBuffer
from app.audit.events import AuditAction, AuditEvent, AuditResult
from app.audit.records import AccessRecord, ApplicationRecord
from app.models.logs import (
    ACTION_LENGTH,
    IP_LENGTH,
    TRACE_ID_LENGTH,
    USER_AGENT_LENGTH,
    AccessLog,
    ApplicationLog,
    AuditLog,
    OperationLog,
    SecurityLog,
)
from app.repositories.logs import TRUNCATION_MARK, LogRepository

pytestmark = pytest.mark.usefixtures("cleanup_generators")

_counter = itertools.count(1)


def _marker() -> str:
    """每次调用返回一个唯一 trace 标记（同时是合法的 trace_id 长度）。"""
    return f"test-{next(_counter):04d}" * 4


def _event(
    action: AuditAction,
    *,
    trace: str,
    resource_type: str = "USER",
    resource_id: int | None = 90001,
    result: AuditResult = AuditResult.SUCCESS,
    after: dict[str, object] | None = None,
    **kwargs: object,
) -> AuditEvent:
    return AuditEvent.build(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        operator_id=91001,
        operator_username="tester",
        result=result,
        after_data=after,
        trace_id=trace,
        **kwargs,
    )


async def _append(session: AsyncSession, buffer: LogBuffer) -> FlushResult:
    return await LogRepository(session).append_buffer(buffer)


async def _audit_rows(session: AsyncSession, trace: str) -> list[AuditLog]:
    result = await session.execute(select(AuditLog).where(AuditLog.trace_id == trace))
    return list(result.scalars().all())


class TestAuditFieldContract:
    """`06 §2` 的 15 个字段一个都不能少。"""

    SPEC_FIELDS = (
        "id",
        "trace_id",
        "request_id",
        "operator_id",
        "operator_username",
        "action",
        "resource_type",
        "resource_id",
        "before_data",
        "after_data",
        "result",
        "error_code",
        "ip",
        "user_agent",
        "created_at",
    )

    def test_audit_table_has_exactly_the_spec_fields(self) -> None:
        assert set(AuditLog.__table__.columns.keys()) == set(self.SPEC_FIELDS)

    def test_audit_log_id_uses_snowflake_bigint(self) -> None:
        column = AuditLog.__table__.columns["id"]
        assert column.primary_key is True
        assert column.autoincrement is False
        assert column.type.python_type is int

    def test_there_is_no_update_or_delete_column(self) -> None:
        """append-only 的第一道防线：结构上就没有可更新的列。"""
        assert "updated_at" not in AuditLog.__table__.columns
        assert "deleted_at" not in AuditLog.__table__.columns


class TestDispatch:
    """一批事件 → 五张表的分发规则。"""

    async def test_empty_buffer_writes_nothing(self, db_session: AsyncSession) -> None:
        result = await _append(db_session, LogBuffer())
        assert result == FlushResult()

    async def test_every_event_reaches_audit_log(self, db_session: AsyncSession) -> None:
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_audit(_event(AuditAction.USER_CREATE, trace=trace))
        buffer.add_audit(_event(AuditAction.AUTH_LOGIN_SUCCESS, trace=trace))
        buffer.add_audit(_event(AuditAction.USER_READ, trace=trace))

        result = await _append(db_session, buffer)

        assert result.audit == 3
        assert len(await _audit_rows(db_session, trace)) == 3

    async def test_security_actions_also_reach_security_log(self, db_session: AsyncSession) -> None:
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_audit(_event(AuditAction.AUTH_LOGIN_FAILURE, trace=trace))
        buffer.add_audit(_event(AuditAction.USER_READ, trace=trace))

        result = await _append(db_session, buffer)

        assert (result.security, result.operation) == (1, 0)
        rows = (
            (await db_session.execute(select(SecurityLog).where(SecurityLog.trace_id == trace)))
            .scalars()
            .all()
        )
        assert [row.event for row in rows] == ["AUTH_LOGIN_FAILURE"]

    async def test_operation_actions_also_reach_operation_log(
        self, db_session: AsyncSession
    ) -> None:
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_audit(_event(AuditAction.USER_CREATE, trace=trace))
        buffer.add_audit(_event(AuditAction.AUTH_LOGOUT, trace=trace))

        result = await _append(db_session, buffer)

        assert (result.operation, result.security) == (1, 1)
        rows = (
            (await db_session.execute(select(OperationLog).where(OperationLog.trace_id == trace)))
            .scalars()
            .all()
        )
        assert [row.action for row in rows] == ["USER_CREATE"]

    async def test_read_only_actions_stay_out_of_operation_log(
        self, db_session: AsyncSession
    ) -> None:
        """只读管理员行为只进审计表（`06 §1` 的 "管理员行为"）。"""
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_audit(_event(AuditAction.PERMISSION_PREVIEW, trace=trace))

        result = await _append(db_session, buffer)

        assert (result.audit, result.operation, result.security) == (1, 0, 0)
        rows = (
            (await db_session.execute(select(SecurityLog).where(SecurityLog.trace_id == trace)))
            .scalars()
            .all()
        )
        assert rows == []

    async def test_access_and_application_logs(self, db_session: AsyncSession) -> None:
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_access(
            AccessRecord(
                method="GET",
                path="/api/v1/admin/health",
                status_code=200,
                duration_ms=7,
                trace_id=trace,
            )
        )
        buffer.add_application(
            ApplicationRecord(level="INFO", logger="app.test", message="hello", trace_id=trace)
        )

        result = await _append(db_session, buffer)

        assert (result.access, result.application) == (1, 1)
        access_row = (
            (await db_session.execute(select(AccessLog).where(AccessLog.trace_id == trace)))
            .scalars()
            .one()
        )
        assert (access_row.method, access_row.path, access_row.status_code) == (
            "GET",
            "/api/v1/admin/health",
            200,
        )
        application_result = await db_session.execute(
            select(ApplicationLog).where(ApplicationLog.trace_id == trace)
        )
        application_row = application_result.scalars().one()
        assert (application_row.level, application_row.logger) == ("INFO", "app.test")
        assert application_row.message == "hello"

    async def test_unclassified_action_keeps_the_audit_row(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """分类失败不得丢掉审计主记录（它才是取证的主体）。

        用一个"新动作忘了分类"的等价场景：把三个集合清空。
        期望：审计表仍有行，安全/操作表没有行 —— 而不是整批消失。
        """
        monkeypatch.setattr("app.audit.classify.SECURITY_ACTIONS", frozenset())
        monkeypatch.setattr("app.audit.classify.OPERATION_ACTIONS", frozenset())
        monkeypatch.setattr("app.audit.classify.READ_ONLY_ACTIONS", frozenset())

        trace = _marker()
        buffer = LogBuffer()
        buffer.add_audit(_event(AuditAction.USER_CREATE, trace=trace))

        result = await _append(db_session, buffer)

        assert (result.audit, result.operation) == (1, 0)
        assert len(await _audit_rows(db_session, trace)) == 1


class TestFailureForensics:
    """失败事件的可诊断信息必须落库（`04 §8`）。"""

    async def test_reason_is_promoted_to_security_log(self, db_session: AsyncSession) -> None:
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_audit(
            _event(
                AuditAction.AUTH_LOCKOUT,
                trace=trace,
                result=AuditResult.FAILURE,
                after={"reason": "LOCKED"},
                error_code=429001,
                resource_type="SESSION",
                resource_id=None,
            )
        )

        await _append(db_session, buffer)

        row = (
            (await db_session.execute(select(SecurityLog).where(SecurityLog.trace_id == trace)))
            .scalars()
            .one()
        )
        assert row.reason == "LOCKED"
        assert row.result == "FAILURE"
        assert row.error_code == 429001

    async def test_missing_reason_stays_null(self, db_session: AsyncSession) -> None:
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_audit(_event(AuditAction.AUTH_LOGIN_SUCCESS, trace=trace))

        await _append(db_session, buffer)

        row = (
            (await db_session.execute(select(SecurityLog).where(SecurityLog.trace_id == trace)))
            .scalars()
            .one()
        )
        assert row.reason is None

    async def test_unknown_operator_is_preserved_as_null(self, db_session: AsyncSession) -> None:
        """ "操作者未知"必须如实为 NULL，不得编造身份。"""
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_audit(
            AuditEvent.build(
                action=AuditAction.AUTH_LOGIN_FAILURE,
                resource_type="SESSION",
                resource_id=None,
                operator_id=None,
                operator_username=None,
                result=AuditResult.FAILURE,
                trace_id=trace,
            )
        )

        await _append(db_session, buffer)

        row = (await _audit_rows(db_session, trace))[0]
        assert row.operator_id is None
        assert row.operator_username is None


class TestOverlongValuesAreClamped:
    """超长值必须被夹住 —— 否则一次请求能让**整批日志**一起丢失。"""

    async def test_long_user_agent_is_truncated_not_rejected(
        self, db_session: AsyncSession
    ) -> None:
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_access(
            AccessRecord(
                method="GET",
                path="/x",
                status_code=200,
                duration_ms=1,
                trace_id=trace,
                user_agent="A" * 60_000,
            )
        )

        result = await _append(db_session, buffer)

        assert result.access == 1
        row = (
            (await db_session.execute(select(AccessLog).where(AccessLog.trace_id == trace)))
            .scalars()
            .one()
        )
        assert len(row.user_agent or "") == USER_AGENT_LENGTH
        assert (row.user_agent or "").endswith(TRUNCATION_MARK)

    async def test_long_path_is_truncated(self, db_session: AsyncSession) -> None:
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_access(
            AccessRecord(
                method="GET",
                path="/" + "p" * 5000,
                status_code=404,
                duration_ms=1,
                trace_id=trace,
            )
        )

        await _append(db_session, buffer)

        row = (
            (await db_session.execute(select(AccessLog).where(AccessLog.trace_id == trace)))
            .scalars()
            .one()
        )
        assert len(row.path) == 512

    async def test_naive_overlong_write_would_have_failed(self, db_session: AsyncSession) -> None:
        """反证：不截断确实会失败。

        直接写超长 UA 会抛数据库异常，而 `flush_logs` 用的是单一独立事务 ——
        失败会连带丢掉**同批次的所有日志**。
        因此截断不是"顺手美化"，而是堵住一条让审计静默消失的通道。
        """
        with pytest.raises(DBAPIError):
            await db_session.execute(
                text(
                    "INSERT INTO audit_logs "
                    "(id, action, resource_type, result, user_agent, created_at) "
                    "VALUES (:id, 'X', 'T', 'SUCCESS', :ua, now())"
                ),
                {"id": 999_000_001, "ua": "A" * 60_000},
            )

    async def test_short_values_are_untouched(self, db_session: AsyncSession) -> None:
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_access(
            AccessRecord(
                method="GET", path="/short", status_code=200, duration_ms=1, trace_id=trace
            )
        )

        await _append(db_session, buffer)

        row = (
            (await db_session.execute(select(AccessLog).where(AccessLog.trace_id == trace)))
            .scalars()
            .one()
        )
        assert row.path == "/short"

    async def test_none_is_not_rewritten_to_empty_string(self, db_session: AsyncSession) -> None:
        """NULL 与空串在检索里语义不同，不得互相转化。"""
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_audit(_event(AuditAction.USER_READ, trace=trace, resource_type="USER"))

        await _append(db_session, buffer)

        row = (await _audit_rows(db_session, trace))[0]
        assert row.ip is None
        assert row.user_agent is None


class TestColumnWidthsMatchConstants:
    """列宽常量与模型定义必须一致（避免"改了常量没改列"）。"""

    def test_trace_id_width(self) -> None:
        assert AuditLog.__table__.columns["trace_id"].type.length == TRACE_ID_LENGTH

    def test_ip_width(self) -> None:
        assert AuditLog.__table__.columns["ip"].type.length == IP_LENGTH

    def test_action_width(self) -> None:
        assert SecurityLog.__table__.columns["event"].type.length == ACTION_LENGTH


class TestTimestampsAndOrder:
    async def test_created_at_round_trips_as_utc(self, db_session: AsyncSession) -> None:
        moment = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_audit(_event(AuditAction.USER_READ, trace=trace, created_at=moment))

        await _append(db_session, buffer)

        row = (await _audit_rows(db_session, trace))[0]
        assert row.created_at.astimezone(UTC) == moment

    async def test_rows_added_later_have_larger_ids(self, db_session: AsyncSession) -> None:
        """Snowflake 单调性在批次内成立 —— 日志的"发生顺序"因此可由主键表达。"""
        trace = _marker()
        first = LogBuffer()
        first.add_audit(_event(AuditAction.USER_READ, trace=trace))
        await _append(db_session, first)

        second = LogBuffer()
        second.add_audit(_event(AuditAction.USER_READ, trace=trace))
        await _append(db_session, second)

        rows = await _audit_rows(db_session, trace)
        assert len(rows) == 2
        assert rows[1].id > rows[0].id


class TestAppendOnlyTriggers:
    """`10 §8` append-only 在**数据库层**强制（第二道防线）。"""

    async def _seed(self, session: AsyncSession) -> tuple[str, int]:
        trace = _marker()
        buffer = LogBuffer()
        buffer.add_audit(_event(AuditAction.USER_CREATE, trace=trace))
        await _append(session, buffer)
        return trace, (await _audit_rows(session, trace))[0].id

    async def test_update_is_rejected(self, db_session: AsyncSession) -> None:
        _, log_id = await self._seed(db_session)
        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(
                text("UPDATE audit_logs SET result = 'FAILURE' WHERE id = :id"),
                {"id": log_id},
            )

    async def test_delete_without_retention_intent_is_rejected(
        self, db_session: AsyncSession
    ) -> None:
        _, log_id = await self._seed(db_session)
        # 显式关闭许可：`SET LOCAL` 的效果持续到事务结束，
        # 前面的用例若开过它，这里必须复位才能验证"未声明意图时被拒绝"。
        await db_session.execute(text("SET LOCAL vctn.retention = 'off'"))
        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": log_id})

    async def test_delete_with_retention_intent_is_allowed(self, db_session: AsyncSession) -> None:
        trace, log_id = await self._seed(db_session)
        await db_session.execute(text("SET LOCAL vctn.retention = 'on'"))
        await db_session.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": log_id})
        assert await _audit_rows(db_session, trace) == []

    async def test_truncate_without_retention_intent_is_rejected(
        self, db_session: AsyncSession
    ) -> None:
        await db_session.execute(text("SET LOCAL vctn.retention = 'off'"))
        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(text("TRUNCATE TABLE operation_logs"))

    @pytest.mark.parametrize(
        "table",
        ["audit_logs", "security_logs", "operation_logs", "access_logs", "application_logs"],
    )
    async def test_every_log_table_has_all_three_triggers(
        self, db_session: AsyncSession, table: str
    ) -> None:
        names = set(
            (
                await db_session.execute(
                    text(
                        "SELECT tgname FROM pg_trigger "
                        "WHERE tgrelid = to_regclass(:table) AND NOT tgisinternal"
                    ),
                    {"table": table},
                )
            )
            .scalars()
            .all()
        )
        assert f"trg_{table}_no_update" in names
        assert f"trg_{table}_no_delete" in names
        assert f"trg_{table}_no_truncate" in names


class TestAppendPathsNeverDelete:
    async def test_append_keeps_ancient_rows(self, db_session: AsyncSession) -> None:
        """落库路径没有任何删除入口（删除只可能来自保留期清理）。"""
        trace = _marker()
        buffer = LogBuffer()
        ancient = datetime.now(UTC) - timedelta(days=9000)
        buffer.add_audit(_event(AuditAction.USER_READ, trace=trace, created_at=ancient))
        await _append(db_session, buffer)
        assert len(await _audit_rows(db_session, trace)) == 1
