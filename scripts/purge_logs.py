"""日志保留期清理入口（Spec `06 §1` / `06 §5` / `07 §8`）。

用法::

    python scripts/purge_logs.py                # 按保留期清理全部五类
    python scripts/purge_logs.py --dry-run      # 只统计待清理行数，不删除
    python scripts/purge_logs.py --category audit --category application

为什么是一个可手动运行的脚本，而不是内建定时任务
----------------------------------------------
`06 §5` 要求"必须提供后续归档 / 清理能力"，`07 §8` 说"高容量日志应考虑
分区与 retention job"。是否**在进程内**跑调度器，取决于部署形态
（单实例 / 多实例 / 外部 cron / Kubernetes CronJob），而这属于部署决策。

把调度交给部署方带来两个确定的好处：
1. 多实例部署下不会出现"N 个实例各跑一遍清理"；
2. 清理的失败可见性落在运维既有的告警通道，而不是应用日志里的一行 ERROR。

因此本项目交付**能力 + 入口**，调度方式登记为 INTERIM-6-07。

输出为什么用 ASCII
-----------------
本机控制台代码页为 GB2312，而脚本可能在 `PYTHONUTF8` 未设置的情况下运行，
中文提示会变成乱码 —— 一条乱码的"清理完成"比英文更难排查。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import dispose_engine, get_session_factory
from app.services.log_retention import (
    RETENTION_DAYS,
    LogRetentionService,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VCTN log retention purge (Spec 06 §1).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count expired rows only, delete nothing",
    )
    parser.add_argument(
        "--category",
        action="append",
        choices=sorted(RETENTION_DAYS),
        default=None,
        help="limit to specific categories (repeatable); default = all",
    )
    return parser.parse_args(argv)


async def _run(*, dry_run: bool, categories: list[str] | None) -> int:
    factory = get_session_factory()
    try:
        async with factory() as session:
            service = LogRetentionService(session)
            if dry_run:
                counts = await service.count_expired()
                for category in sorted(counts):
                    print(f"[dry-run] {category}: {counts[category]} row(s) expired")
                return 0

            report = await service.purge(categories=categories)
            for category in sorted(report.deleted):
                print(
                    f"[purged] {category}: {report.deleted[category]} row(s), "
                    f"cutoff={report.cutoff[category].isoformat()}"
                )
            print(f"[done] total deleted = {report.total}")
            return 0
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    """脚本入口。返回进程退出码。"""
    args = _parse_args(argv)
    return asyncio.run(_run(dry_run=bool(args.dry_run), categories=args.category))


if __name__ == "__main__":
    raise SystemExit(main())
