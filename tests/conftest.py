"""pytest 全局夹具。

设计约束：
- Phase 1 环境中可能**没有可用**的 PostgreSQL / Redis，
  因此测试默认不依赖任何外部组件；
  依赖可用性相关的分支通过 monkeypatch 显式模拟。
- ASGITransport 不触发 lifespan，避免启动期依赖探测影响测试耗时与稳定性。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

# 必须在导入应用模块之前设置，保证 settings 单例读取到测试值
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("DEBUG", "false")
# 指向不可达端口：连接被立即拒绝，探针快速失败而非等待超时
os.environ.setdefault("POSTGRES_HOST", "127.0.0.1")
os.environ.setdefault("POSTGRES_PORT", "1")
os.environ.setdefault("REDIS_HOST", "127.0.0.1")
os.environ.setdefault("REDIS_PORT", "1")

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_app


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
