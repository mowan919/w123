"""只读数据库巡检（Phase 9：关键索引 / 外键 / 约束）。

用途：把"数据库关键索引存在"与"FK 行为符合逻辑删除设计"两项验收
建立在**实查**结果上，而不是代码上的 `__table_args__` 声明 ——
后者只证明"迁移里写了"，不证明"库里真的有"。

只读：不执行任何 DDL / DML。
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings


async def main() -> None:
    url = settings.database_url
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        print("=" * 78)
        print("1. 索引（public schema）")
        print("=" * 78)
        rows = (
            await conn.execute(
                text(
                    "select tablename, indexname from pg_indexes "
                    "where schemaname='public' order by tablename, indexname"
                )
            )
        ).all()
        print(f"总数：{len(rows)}")
        current = ""
        for table, index in rows:
            if table != current:
                print(f"\n[{table}]")
                current = table
            print(f"  {index}")

        print()
        print("=" * 78)
        print("2. 外键及其删除行为")
        print("   confdeltype: a=NO ACTION r=RESTRICT c=CASCADE n=SET NULL d=SET DEFAULT")
        print("=" * 78)
        fks = (
            await conn.execute(
                text(
                    """
                    select c.conname, cl.relname as tbl, clf.relname as reftbl, c.confdeltype
                    from pg_constraint c
                    join pg_class cl on cl.oid = c.conrelid
                    join pg_class clf on clf.oid = c.confrelid
                    where c.contype = 'f' and c.connamespace = 'public'::regnamespace
                    order by cl.relname, c.conname
                    """
                )
            )
        ).all()
        print(f"总数：{len(fks)}")
        bad = [f for f in fks if f[3] == "c"]
        for name, tbl, reftbl, deltype in fks:
            flag = "  <== CASCADE" if deltype == "c" else ""
            print(f"  {tbl:28} {name:48} -> {reftbl}{flag}")
        print(f"\nCASCADE 外键数量：{len(bad)}")

        print()
        print("=" * 78)
        print("3. 逻辑删除相关：含 deleted_at 的表")
        print("=" * 78)
        cols = (
            await conn.execute(
                text(
                    "select table_name, column_name from information_schema.columns "
                    "where table_schema='public' and column_name='deleted_at' "
                    "order by table_name"
                )
            )
        ).all()
        for table, _column in cols:
            print(f"  {table}")

        print()
        print("=" * 78)
        print("4. partial unique index（软删除感知唯一性）")
        print("=" * 78)
        partial = (
            await conn.execute(
                text(
                    "select c.relname, pg_get_indexdef(i.indexrelid) "
                    "from pg_index i join pg_class c on c.oid = i.indexrelid "
                    "where i.indpred is not null and c.relnamespace='public'::regnamespace"
                )
            )
        ).all()
        for name, ddl in partial:
            print(f"  {name}\n      {ddl}")

    await engine.dispose()
    print()
    print("巡检完成（只读）。")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
