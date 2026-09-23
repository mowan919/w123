"""依赖连通性检查脚本。

用途：Phase 1 环境基线验收 —— 验证应用能真实连上 PostgreSQL 与 Redis。

    .\\scripts\\dev.ps1 -Action db-check
    或
    .venv\\Scripts\\python.exe scripts\\check_deps.py

设计约束：
- **只读**：仅执行 `SELECT 1` / `SELECT version()` / `PING` / `INFO server`，
  不创建、不修改、不删除任何数据与结构。
- **凭据不外泄**：所有输出走 `database_url_safe` / `redis_url_safe`，密码永不打印。
- 退出码：0 = 全部可用；1 = 存在不可用依赖（fail-closed，便于 CI 判定）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 允许以脚本方式直接运行（把项目根加入 sys.path）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.redis import check_redis, close_redis, get_redis  # noqa: E402
from app.db.session import check_database, dispose_engine, get_engine  # noqa: E402

OK = "[ OK ]"
FAIL = "[FAIL]"


async def _check_postgres() -> bool:
    print("--- PostgreSQL ---")
    print(f"  target   : {settings.database_url_safe}")
    try:
        await check_database()
    except Exception as exc:  # 需要报告任意连接失败
        print(f"  {FAIL} {type(exc).__name__}: {exc}")
        return False

    try:
        async with get_engine().connect() as connection:
            version = (await connection.execute(text("SELECT version()"))).scalar_one()
            database, user = (
                await connection.execute(text("SELECT current_database(), current_user"))
            ).one()
            encoding = (await connection.execute(text("SHOW server_encoding"))).scalar_one()
        print(f"  {OK} connected")
        print(f"  server   : {version.split(',')[0]}")
        print(f"  database : {database}")
        print(f"  user     : {user}")
        print(f"  encoding : {encoding}")
        return True
    except Exception as exc:
        print(f"  {FAIL} 连通后查询失败：{type(exc).__name__}: {exc}")
        return False
    finally:
        await dispose_engine()


async def _check_redis() -> bool:
    print("--- Redis ---")
    print(f"  target   : {settings.redis_url_safe}")
    try:
        await check_redis()
    except Exception as exc:
        print(f"  {FAIL} {type(exc).__name__}: {exc}")
        return False

    try:
        client = get_redis()
        server_info = await client.info("server")
        print(f"  {OK} connected (PING)")
        print(f"  version  : {server_info.get('redis_version')}")
        print(f"  mode     : {server_info.get('redis_mode')}")
        return True
    except Exception as exc:
        print(f"  {FAIL} 连通后查询失败：{type(exc).__name__}: {exc}")
        return False
    finally:
        await close_redis()


async def _main() -> int:
    print("=== VCTN 依赖连通性检查 ===")
    print(f"  app_env  : {settings.app_env}")
    print()

    postgres_ok = await _check_postgres()
    print()
    redis_ok = await _check_redis()
    print()

    if postgres_ok and redis_ok:
        print("[OK] 全部依赖可用。")
        return 0
    print("[FAIL] 存在不可用依赖。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
