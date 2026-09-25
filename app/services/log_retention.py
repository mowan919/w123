"""日志保留期清理（Spec `06 §1` / `06 §5` / `07 §8`）。

Frozen 保留期
-----------
| 类别 | 保留期（`06 §1`） |
|---|---|
| Access Log | 30 days |
| Security Log | 180 days |
| Operation Log | 180 days |
| Audit Log | 2 years |
| Application Log | 30 days |

为什么天数写死在代码里，不做成配置
--------------------------------
保留期是 Spec 冻结值，不是运维偏好。做成配置项就等于提供了一条
**静默缩短保留期**的通道 —— 改一个环境变量，2 年的审计历史变成 7 天，
而代码、评审、测试都不会有任何变化。要改保留期就必须改代码，
那就必须走评审。这与"不得自行弱化安全要求"是同一条规则。

2 年为什么落成 730 天
-------------------
`06 §1` 写 "2 years"，未规定按**日历年**（含闰年，实际 730 或 731 天）
还是按 **365 天 × 2**。本实现取 730 天：它不依赖"当前是哪个日历区间"，
同一份代码在任何日期跑出的边界都一致，因此可被测试精确断言。
差异最多 1 天，且方向不确定（不是"一律更短"），登记为 INTERIM-6-05。

为什么必须用触发器而不是普通删除
------------------------------
`audit_logs` 等五张表上有 `BEFORE DELETE` 触发器（迁移 `phase6_dd08`），
只有设置了会话变量 `vctn.retention = 'on'` 才允许删除。
因此**保留期清理走 `SET LOCAL`**，而业务代码没有任何删除入口。
`SET LOCAL` 是事务作用域的：提交后自动失效，
不需要（也不应该）担心它"泄漏"到下一个请求上。

事务边界：一次清理 = 一个事务
---------------------------
`SET LOCAL` 一旦跨事务就失效，因此所有类别的删除必须**在同一事务内**完成，
然后一次性提交。顺带得到原子性：要么五类都清理到同一时点，
要么一行都不动 —— 不会出现"审计清了、安全日志没清"的半成品状态。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult

from app.db.base import utc_now
from app.models.logs import LOG_MODELS

#: 允许删除的会话变量（与迁移 `phase6_dd08` 的触发器判定值一致）。
RETENTION_GUC = "vctn.retention"
RETENTION_GUC_VALUE = "on"

#: `06 §1` 的保留期（不可配置，见模块文档）。
RETENTION_DAYS: Mapping[str, int] = MappingProxyType(
    {
        "access": 30,
        "security": 180,
        "operation": 180,
        "audit": 730,
        "application": 30,
    }
)

#: 开启删除许可的语句。
#
# `SET LOCAL` 的 `LOCAL` 不可省略：`SET` 会改到会话级别，
# 而连接回到池里会被下一个请求复用 —— 那就等于给所有连接永久开了删除权限。
_ENABLE_DELETE = text(f"SET LOCAL {RETENTION_GUC} = '{RETENTION_GUC_VALUE}'")


@dataclass(frozen=True, slots=True)
class PurgeReport:
    """一次清理的结果。"""

    deleted: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    cutoff: Mapping[str, datetime] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def total(self) -> int:
        """删除总行数。"""
        return sum(self.deleted.values())


def _rowcount(result: Any) -> int:
    """从 `DELETE` 的执行结果取受影响行数。

    为什么这里用 `rowcount`（而本仓库其它删除走 `RETURNING id`）
    ---------------------------------------------------------
    其它仓储用 `RETURNING id` 是为了绕开"`Result` 抽象类型上没有 `rowcount`"
    这个类型问题。保留期清理不能照搬：审计表 2 年、安全日志 180 天，
    一次清理可能命中**数百万行**，`RETURNING id` 会把它们全部物化到内存，
    只为算一个计数。

    类型问题在这里用显式 `cast` 解决：`rowcount` 确实是 `CursorResult`
    的公开接口，只是 `AsyncSession.execute` 的声明返回类型更宽。
    用 `cast` 表达"我知道实际拿到的是游标结果"，
    比为了迁就声明类型而制造 O(命中行数) 的内存开销更合理。
    """
    return int(cast("CursorResult[Any]", result).rowcount or 0)


def cutoff_for(category: str, *, now: datetime | None = None) -> datetime:
    """返回某类别的清理边界（严格早于该时刻的行会被删除）。

    Raises:
        KeyError: 类别不存在。
    """
    if category not in RETENTION_DAYS:
        raise KeyError(f"未知日志类别：{category}")
    moment = now or utc_now()
    return moment - timedelta(days=RETENTION_DAYS[category])


class LogRetentionService:
    """按 `06 §1` 的保留期清理五类日志。

    只做清理，不做归档。`06 §5` 允许"分区、归档或批量清理"三种方式，
    本项目选批量清理（理由见 `docs/DESIGN-DECISIONS.md`）；
    归档需要外部存储目标，属部署期决策，不在代码里假定。
    """

    __slots__ = ("_session",)

    def __init__(self, session: AsyncSession) -> None:
        """绑定会话。提交边界由本服务掌握（见模块文档）。"""
        self._session = session

    async def purge(
        self,
        *,
        now: datetime | None = None,
        categories: Sequence[str] | None = None,
    ) -> PurgeReport:
        """删除超过保留期的日志行。

        Args:
            now: 计算边界的"现在"（测试注入固定时刻用）。
            categories: 只清理这些类别；`None` 表示全部（默认，也是调度用法）。

        Returns:
            每类别的删除行数与所用边界。

        Raises:
            KeyError: 传入未知类别 —— 静默忽略拼错的类别会让"以为清了"成真。
        """
        targets = tuple(categories) if categories is not None else tuple(RETENTION_DAYS)
        for category in targets:
            if category not in LOG_MODELS:
                raise KeyError(f"未知日志类别：{category}")

        if not targets:
            return PurgeReport()

        # 许可与全部删除必须在同一事务：`SET LOCAL` 是事务作用域的。
        await self._session.execute(_ENABLE_DELETE)

        deleted: dict[str, int] = {}
        cutoffs: dict[str, datetime] = {}
        for category in targets:
            cutoff = cutoff_for(category, now=now)
            model = LOG_MODELS[category]
            result = await self._session.execute(delete(model).where(model.created_at < cutoff))
            deleted[category] = _rowcount(result)
            cutoffs[category] = cutoff

        await self._session.commit()

        return PurgeReport(
            deleted=MappingProxyType(deleted),
            cutoff=MappingProxyType(cutoffs),
        )

    async def count_expired(self, *, now: datetime | None = None) -> dict[str, int]:
        """统计各类别的**待清理行数**（只读，不触发任何删除）。

        存在的理由是让"清理任务是否在正常工作"可观测：
        只报告"删了 0 行"无法区分"没有过期数据"与"清理一直在失败"。
        """
        counts: dict[str, int] = {}
        for category, model in LOG_MODELS.items():
            cutoff = cutoff_for(category, now=now)
            result = await self._session.execute(
                select(func.count()).select_from(model).where(model.created_at < cutoff)
            )
            counts[category] = int(result.scalar_one())
        return counts


__all__ = [
    "RETENTION_DAYS",
    "RETENTION_GUC",
    "RETENTION_GUC_VALUE",
    "LogRetentionService",
    "PurgeReport",
    "cutoff_for",
]
