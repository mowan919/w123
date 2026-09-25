"""日志保留期清理（Spec `06 §1` / `06 §5` / `07 §8`）。

保留期是 Frozen 值：30 / 180 / 180 / 2 年 / 30 天。
本模块既验证"天数对不对"，也验证"清理**真的**只删过期行"
（`06 §5` 的措辞是"必须提供后续归档/清理能力"，
只提供一个能跑但删错行的函数不算提供能力）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.buffer import LogBuffer
from app.audit.events import AuditAction, AuditEvent
from app.audit.records import AccessRecord, ApplicationRecord
from app.models.logs import (
    LOG_MODELS,
    AccessLog,
    ApplicationLog,
    AuditLog,
    OperationLog,
    SecurityLog,
)
from app.repositories.logs import LogRepository
from app.services.log_retention import (
    RETENTION_DAYS,
    RETENTION_GUC,
    LogRetentionService,
    cutoff_for,
)

pytestmark = pytest.mark.usefixtures("cleanup_generators")

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

#: 每个类别一个唯一 trace 前缀，避免读到库里已提交的历史行。
PREFIX = "retentiontest"


class TestFrozenRetentionPeriods:
    """`06 §1` 的保留期一个都不能改。"""

    def test_days_match_spec(self) -> None:
        assert dict(RETENTION_DAYS) == {
            "access": 30,
            "security": 180,
            "operation": 180,
            "audit": 730,
            "application": 30,
        }

    def test_audit_is_two_years(self) -> None:
        """Spec 写 "2 years"；实现取 730 天（见模块文档的 INTERIM 说明）。

        这里断言的是**下界**：审计保留期必须显著长于其余四类，
        否则"高价值记录"与"普通操作"就只剩表名差异。
        """
        assert RETENTION_DAYS["audit"] >= 365 * 2
        assert RETENTION_DAYS["audit"] > RETENTION_DAYS["security"]
        assert RETENTION_DAYS["security"] > RETENTION_DAYS["access"]

    def test_configuration_cannot_shorten_retention(self) -> None:
        """保留期不可配置 —— 否则一条环境变量就能把 2 年审计变成 7 天。"""
        with pytest.raises(TypeError):
            RETENTION_DAYS["audit"] = 7  # type: ignore[index]

    def test_every_log_model_has_a_retention_period(self) -> None:
        """新增日志表却忘了定保留期 → 它会被"永久保留"且无人察觉。"""
        assert set(LOG_MODELS) == set(RETENTION_DAYS)


class TestCutoff:
    @pytest.mark.parametrize(
        ("category", "days"),
        [
            ("access", 30),
            ("security", 180),
            ("operation", 180),
            ("audit", 730),
            ("application", 30),
        ],
    )
    def test_cutoff_is_now_minus_days(self, category: str, days: int) -> None:
        assert cutoff_for(category, now=NOW) == NOW - timedelta(days=days)

    def test_unknown_category_raises(self) -> None:
        with pytest.raises(KeyError):
            cutoff_for("auditv2", now=NOW)

    def test_default_now_is_utc_now(self) -> None:
        before = datetime.now(UTC) - timedelta(days=30)
        assert cutoff_for("access") >= before


async def _seed(
    session: AsyncSession,
    *,
    category: str,
    age_days: int,
    tag: str,
    created_at: datetime | None = None,
) -> None:
    """插入一条指定年龄的日志行。"""
    moment = created_at if created_at is not None else NOW - timedelta(days=age_days)
    trace = f"{PREFIX}-{category}-{tag}"
    buffer = LogBuffer()

    if category == "audit":
        buffer.add_audit(
            AuditEvent.build(
                action=AuditAction.USER_READ,
                resource_type="USER",
                resource_id=1,
                operator_id=1,
                operator_username="t",
                trace_id=trace,
                created_at=moment,
            )
        )
    elif category == "security":
        buffer.add_audit(
            AuditEvent.build(
                action=AuditAction.AUTH_LOGIN_SUCCESS,
                resource_type="SESSION",
                resource_id=None,
                operator_id=1,
                operator_username="t",
                trace_id=trace,
                created_at=moment,
            )
        )
    elif category == "operation":
        buffer.add_audit(
            AuditEvent.build(
                action=AuditAction.USER_CREATE,
                resource_type="USER",
                resource_id=1,
                operator_id=1,
                operator_username="t",
                trace_id=trace,
                created_at=moment,
            )
        )
    elif category == "access":
        buffer.add_access(
            AccessRecord(
                method="GET",
                path="/__retention__",
                status_code=200,
                duration_ms=1,
                trace_id=trace,
                created_at=moment,
            )
        )
    elif category == "application":
        buffer.add_application(
            ApplicationRecord(
                level="INFO", logger="app.test", message="x", trace_id=trace, created_at=moment
            )
        )
    else:  # pragma: no cover - 测试自身的用法错误
        raise AssertionError(f"未知类别 {category}")

    await LogRepository(session).append_buffer(buffer)


async def _count(session: AsyncSession, category: str, tag: str) -> int:
    model = LOG_MODELS[category]
    trace = f"{PREFIX}-{category}-{tag}"
    column = model.trace_id
    rows = (await session.execute(select(model).where(column == trace))).scalars().all()
    return len(rows)


class TestPurge:
    async def test_expired_rows_are_deleted_and_fresh_rows_survive(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, category="access", age_days=31, tag="old")
        await _seed(db_session, category="access", age_days=29, tag="new")

        report = await LogRetentionService(db_session).purge(now=NOW)

        assert report.deleted["access"] == 1
        assert await _count(db_session, "access", "old") == 0
        assert await _count(db_session, "access", "new") == 1

    async def test_boundary_is_strictly_older_than_cutoff(self, db_session: AsyncSession) -> None:
        """恰好落在边界上的行**保留**（实现用严格小于）。

        边界语义必须确定：如果边界用 `<=`，那么一条记录会在"满 30 天"的
        那一瞬间被删除，保留期实际变成 29 天 23 小时 59 分 —— 一个无法从
        Spec 文字读出来、却真实存在的缩短。
        """
        await _seed(db_session, category="access", age_days=30, tag="exact")
        await _seed(
            db_session,
            category="access",
            age_days=30,
            tag="just-older",
            created_at=NOW - timedelta(days=30, seconds=1),
        )

        await LogRetentionService(db_session).purge(now=NOW, categories=["access"])

        assert await _count(db_session, "access", "exact") == 1
        assert await _count(db_session, "access", "just-older") == 0

    async def test_each_category_uses_its_own_period(self, db_session: AsyncSession) -> None:
        """同一个"200 天前"的行：30 天与 180 天的类别清除，2 年的类别保留。"""
        for category in ("access", "security", "operation", "audit", "application"):
            await _seed(db_session, category=category, age_days=200, tag="200d")

        report = await LogRetentionService(db_session).purge(now=NOW)

        assert report.deleted == {
            "access": 1,
            "security": 1,
            "operation": 1,
            "audit": 0,
            "application": 1,
        }
        assert await _count(db_session, "audit", "200d") == 1

    async def test_audit_survives_two_years_of_security_cleanup(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, category="audit", age_days=700, tag="700d")
        await _seed(db_session, category="security", age_days=700, tag="700d")

        await LogRetentionService(db_session).purge(now=NOW)

        assert await _count(db_session, "audit", "700d") == 1
        assert await _count(db_session, "security", "700d") == 0

    async def test_audit_is_purged_after_two_years(self, db_session: AsyncSession) -> None:
        await _seed(db_session, category="audit", age_days=731, tag="731d")

        report = await LogRetentionService(db_session).purge(now=NOW)

        assert report.deleted["audit"] == 1
        assert await _count(db_session, "audit", "731d") == 0

    async def test_category_filter_limits_scope(self, db_session: AsyncSession) -> None:
        await _seed(db_session, category="access", age_days=400, tag="bad")
        await _seed(db_session, category="audit", age_days=400, tag="bad")

        report = await LogRetentionService(db_session).purge(now=NOW, categories=["access"])

        assert dict(report.deleted) == {"access": 1}
        assert await _count(db_session, "audit", "bad") == 1

    async def test_unknown_category_is_rejected_before_any_delete(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, category="access", age_days=400, tag="keep")

        with pytest.raises(KeyError):
            await LogRetentionService(db_session).purge(now=NOW, categories=["access", "nope"])

        assert await _count(db_session, "access", "keep") == 1

    async def test_empty_category_list_is_a_noop(self, db_session: AsyncSession) -> None:
        report = await LogRetentionService(db_session).purge(now=NOW, categories=[])
        assert report.total == 0

    async def test_uses_retention_transaction_guc(self, db_session: AsyncSession) -> None:
        """许可与删除必须在同一事务 —— 否则 DELETE 会被触发器拒绝。

        这是一个"正向断言"：如果实现忘了 `SET LOCAL`，
        `purge()` 会抛 append-only 违规而不是安静地少删几行。
        """
        await _seed(db_session, category="access", age_days=400, tag="need-guc")
        await db_session.execute(text(f"SET LOCAL {RETENTION_GUC} = 'off'"))

        report = await LogRetentionService(db_session).purge(now=NOW, categories=["access"])

        assert report.deleted["access"] == 1


class TestCountExpired:
    async def test_counts_without_deleting(self, db_session: AsyncSession) -> None:
        await _seed(db_session, category="access", age_days=400, tag="stale")

        counts = await LogRetentionService(db_session).count_expired(now=NOW)

        assert counts["access"] >= 1
        assert await _count(db_session, "access", "stale") == 1

    async def test_reports_zero_after_purge(self, db_session: AsyncSession) -> None:
        await _seed(db_session, category="application", age_days=400, tag="stale")

        service = LogRetentionService(db_session)
        await service.purge(now=NOW, categories=["application"])

        # purge 提交后，本次事务内插入的过期行已被删除
        rows = (
            (
                await db_session.execute(
                    select(ApplicationLog).where(
                        ApplicationLog.trace_id == f"{PREFIX}-application-stale"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


class TestModelRegistration:
    def test_all_five_tables_are_registered(self) -> None:
        assert set(LOG_MODELS) == {"access", "security", "operation", "audit", "application"}

    def test_models_map_to_expected_tables(self) -> None:
        assert LOG_MODELS["audit"] is AuditLog
        assert LOG_MODELS["security"] is SecurityLog
        assert LOG_MODELS["operation"] is OperationLog
        assert LOG_MODELS["access"] is AccessLog
        assert LOG_MODELS["application"] is ApplicationLog
