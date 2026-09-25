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
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 不得在模块级导入应用模块，理由见下方 `_inject` 区块的说明
    from app.core.rate_limit import InMemoryRateLimitBackend

# ⚠️ 本文件在 `_inject(...)` 之前**不得**导入任何应用模块：
# `app.core.config.settings` 是导入期构造的单例，一旦被提前导入，
# 它读到的是 `.env` 的真实值而不是下面的测试注入值
# （后果之一：`MFA_ENCRYPTION_KEY` 为空 → 所有涉 Secret 用例以
# `ConfigurationError` 失败）。因此 `app.core.rate_limit` 的导入
# 放在 `isolate_rate_limiter` 夹具**内部**。

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
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.main import create_app  # noqa: E402

# ---------------------------------------------------------------------------
# 日志落库隔离（Phase 6）
# ---------------------------------------------------------------------------


class _NullSession:
    """吞掉所有写入的会话替身（见 `isolate_log_flush`）。"""

    async def execute(self, *args: Any, **kwargs: Any) -> None:
        """什么也不做。"""
        return None

    async def commit(self) -> None:
        """什么也不做。"""
        return None

    async def rollback(self) -> None:
        """什么也不做。"""
        return None

    async def close(self) -> None:
        """什么也不做。"""
        return None


@asynccontextmanager
async def _null_session_provider() -> AsyncIterator[_NullSession]:
    """提供一个不落库的会话。"""
    yield _NullSession()


@pytest.fixture(autouse=True)
def isolate_rate_limiter() -> Iterator[InMemoryRateLimitBackend]:
    """把限流后端换成**进程内**实现，并让每个用例从零开始。

    为什么必须全局替换
    ------------------
    Phase 9 起 `POST /auth/login` 与 `POST /auth/mfa/verify` 每次调用都会
    消耗真实 Redis 的配额。测试里登录相关的用例有几十条、且共用同一个
    客户端 IP，若走真实 Redis，会撞上"每 IP 每分钟 N 次"的上限 ——
    症状是**第 N 个用例突然 429**，而它失败与否取决于同一分钟内
    跑过多少其它用例。那是典型的测试间耦合：单独跑能过、整套跑就红，
    而且红的位置每次都可能不同。

    换成内存后端后计数既真实（同一用例内会累加、超限会 429）
    又彻底隔离（用例之间归零）。需要验证 **Redis 后端本身**的用例
    自行构造 `RedisRateLimitBackend`（见 `tests/test_rate_limit.py`）。

    Returns:
        内存后端，用例可调用 `.reset()` 手动清零。
    """
    from app.core import rate_limit as rate_limit_module

    backend = rate_limit_module.InMemoryRateLimitBackend()
    previous = rate_limit_module._limiter
    rate_limit_module.set_rate_limiter(rate_limit_module.RateLimiter(backend, fail_open=True))
    try:
        yield backend
    finally:
        rate_limit_module.set_rate_limiter(previous)


@pytest.fixture(autouse=True)
def isolate_log_flush() -> Iterator[None]:
    """把日志落库限制在测试进程内（不连数据库、不跨用例残留）。

    为什么需要它
    -----------
    每个 HTTP 请求结束时中间件都会调用 `flush_logs()`（Phase 6）。
    若走默认提供者，**每一个**请求都会去连 `.env` 指向的数据库 ——
    而在测试期那是一个不可达端口，于是每次请求都产生一次连接失败
    外加一条 ERROR 堆栈。

    结果不是"测试失败"，而是"几百条与用例无关的噪音混进输出"，
    以及 `flush_failures` 这个全局计数被污染（需要它的用例将失去意义）。

    替换成吞掉写入的会话替身之后：
    - HTTP 用例不再需要数据库；
    - 计数从 0 开始，断言可靠；
    - 需要**真实**落库的用例自行注入提供者 —— 见
      `tests/test_trace_access_log.py::flush_into_session`。
    """
    from app.audit import buffer as log_buffer

    def _reset() -> None:
        log_buffer.set_session_provider(_null_session_provider)
        log_buffer.drain()
        log_buffer.flush_failures = 0
        log_buffer.dropped_logs = 0
        log_buffer.reset_circuit()

    _reset()
    try:
        yield
    finally:
        _reset()
        log_buffer.set_session_provider(None)


@pytest_asyncio.fixture
async def real_redis_client() -> AsyncIterator[object]:
    """提供一个**真实 Redis** 客户端（指向 `.env` 的实例）。

    为什么需要它
    -----------
    本文件把 `REDIS_HOST/PORT` 注入成不可达端口，于是任何"打真实 Redis"
    的用例都会失败 —— 合理地失败，但也就**永远无法被验证**。
    Phase 9 的限流后端正属于这一类：内存后端再正确，也证明不了
    `INCR` + `EXPIRE` 的 pipeline 与 TTL 语义在 Redis 上成立，
    而"TTL 没设上"的后果是永久封禁某个主体。

    做法与 `_real_database_url()` 同口径：临时移除本文件注入的
    `REDIS_*`，构造一个全新的客户端，用完关闭并还原。

    用例应当在 Redis 不可达时 **skip** 而不是 fail —— 那是环境问题，
    不是代码缺陷（两种结果在验收报告里必须区分开）。
    """
    saved: dict[str, str] = {}
    for key in list(_INJECTED):
        if key.startswith("REDIS"):
            saved[key] = os.environ.pop(key)
    client = None
    try:
        from redis.asyncio import Redis

        from app.core.config import Settings

        fresh = Settings()
        client = Redis.from_url(
            fresh.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=fresh.redis_socket_timeout,
            socket_connect_timeout=fresh.redis_socket_timeout,
        )
        yield client
    finally:
        if client is not None:
            # 关闭失败不得掩盖用例结论（连接可能已经断开）；
            # 用 suppress 而不是 try/except/pass，避免 lint 把它当成"吞异常"。
            with suppress(Exception):
                await client.aclose()
        os.environ.update(saved)


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
