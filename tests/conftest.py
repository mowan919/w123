"""pytest 全局夹具。

设计约束
-------
1. Phase 1 起的测试默认**不依赖任何外部组件**：
   环境变量被指向不可达端口，依赖可用性分支由 monkeypatch 显式模拟。
2. **数据库集成测试**需要真实 PostgreSQL，通过 `db_session` 夹具获得：
   - 单独构造 engine，**绕过**测试期注入的哨兵覆盖（读 `.env`）；
   - 每个用例跑在一个外层事务里，结束**回滚**，因此不会污染数据库，
     也不需要"测试库"这一额外环境（Phase 2 的隔离方案）。
3. `ASGITransport` 不触发 lifespan，避免启动期依赖探测影响测试耗时与稳定性。
"""

from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

# 必须在导入应用模块之前设置，保证 settings 单例读取到测试值
# 记录"由本文件注入"的键，供数据库夹具精确还原（见 _real_database_url）
_INJECTED: dict[str, str] = {}


def _inject(key: str, value: str) -> None:
    """等价于 `os.environ.setdefault`，但记录注入来源。"""
    if key not in os.environ:
        os.environ[key] = value
        _INJECTED[key] = value


_inject("APP_ENV", "test")
_inject("LOG_LEVEL", "WARNING")
_inject("LOG_JSON", "false")
_inject("DEBUG", "false")
# 指向不可达端口：连接被立即拒绝，探针快速失败而非等待超时
_inject("POSTGRES_HOST", "127.0.0.1")
_inject("POSTGRES_PORT", "1")
_inject("REDIS_HOST", "127.0.0.1")
_inject("REDIS_PORT", "1")

# MFA Secret 的 AEAD 密钥（DD-22）：测试需要一条**确定**的 32 字节 base64 密钥。
# 为什么必须注入而不是依赖 `.env`：`.env.example` 刻意把它留空
# （真实部署由环境/密钥管理注入，Spec `13 §2`），若测试沿用该空值，
# 所有涉及 Secret 的用例都会以 `ConfigurationError` 失败 ——
# 那会让"加密保存"这条验收项**永远无法被验证**。
# 用 sha256 摘要构造是为了得到长度确定（32 字节）且可复现的密钥；
# 它只是测试夹具，不含任何真实部署密钥。
_inject(
    "MFA_ENCRYPTION_KEY",
    base64.b64encode(hashlib.sha256(b"vctn-test-mfa-encryption-key").digest()).decode(),
)

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.main import create_app  # noqa: E402


def _real_database_url() -> str | None:
    """读取 `.env` 中的真实数据库连接串。

    测试期注入的哨兵值会被临时移除，从而让 `Settings` 回落到 `.env`。
    只移除**本文件注入过**的键，开发者自己 export 的值不受影响。
    """
    saved: dict[str, str] = {}
    for key in list(_INJECTED):
        if key.startswith("POSTGRES"):
            saved[key] = os.environ.pop(key)
    try:
        from app.core.config import Settings

        fresh = Settings()
    except Exception:  # pragma: no cover - 配置缺失时视为不可用
        return None
    finally:
        os.environ.update(saved)
    return fresh.database_url


@pytest.fixture(scope="session")
def app() -> FastAPI:
    """测试用 FastAPI 应用。"""
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """异步 HTTP 客户端，直接对 ASGI 应用发起请求。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://vctn.test") as http_client:
        yield http_client


@pytest.fixture
def api_prefix() -> str:
    return "/api/v1/admin"


@pytest.fixture
def cleanup_generators() -> Iterator[None]:
    """确保 Snowflake 全局生成器在测试后被重置。"""
    from app.core.snowflake import reset_generator

    reset_generator()
    yield
    reset_generator()


@pytest.fixture
def temp_routes(app: FastAPI) -> Iterator[FastAPI]:
    """为测试临时挂载路由，结束后移除，避免污染其他用例。"""
    original_count = len(app.router.routes)
    yield app
    del app.router.routes[original_count:]


# ---------------------------------------------------------------------------
# 数据库集成测试夹具
# ---------------------------------------------------------------------------
@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """真实数据库会话，外层事务包裹，用例结束后回滚。

    为什么用 `NullPool`：每个用例一个连接、用后即弃，
    避免长连接残留在测试进程里。
    """
    url = _real_database_url()
    if url is None:
        pytest.skip("未配置 PostgreSQL 连接（.env 缺失或无法构造 Settings）")

    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            # 必须先 begin()，否则探针查询会 autobegin，导致后续 begin() 失败
            transaction = await connection.begin()
            try:
                await connection.execute(text("select 1"))
            except Exception as exc:  # pragma: no cover - 环境相关
                await transaction.rollback()
                pytest.skip(f"PostgreSQL 不可达：{type(exc).__name__}")

            session = AsyncSession(bind=connection, expire_on_commit=False, autoflush=False)
            try:
                yield session
            finally:
                await session.close()
                await transaction.rollback()
    finally:
        await engine.dispose()


class RecordingAuditRecorder:
    """记录审计事件的测试替身（实现 `AuditRecorder` 端口）。"""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)

    # -- 断言辅助 --
    def actions(self) -> list[str]:
        return [str(event.action) for event in self.events]

    def results(self) -> list[str]:
        return [str(event.result) for event in self.events]

    def find(self, action: str) -> Any | None:
        for event in self.events:
            if str(event.action) == action:
                return event
        return None

    def failures(self) -> list[Any]:
        return [event for event in self.events if str(event.result) == "FAILURE"]


@pytest.fixture
def audit_recorder() -> RecordingAuditRecorder:
    """可断言的审计记录器。"""
    return RecordingAuditRecorder()
