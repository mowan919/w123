"""PostgreSQL / SQLAlchemy 异步基础设施。

Spec 07 §1：PostgreSQL + SQLAlchemy + Alembic。
Spec 13 §4：health 必须包含 database health。

设计说明：
- engine 采用**惰性创建**，import 时不连接数据库。
  这样在没有可用 PostgreSQL 实例的环境中（例如当前开发机），
  应用仍可正常启动并暴露 liveness 探针，数据库状态由 readiness 探针表达。
- 本阶段不定义任何业务表，也不生成业务 migration。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """返回进程级 AsyncEngine（惰性初始化）。"""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.db_echo,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
        )
        logger.info("database_engine_created url=%s", settings.database_url_safe)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """返回进程级 Session 工厂。"""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：提供一个请求级 Session。

    默认不自动提交：写操作由 Service 层显式 commit，
    避免权限类写操作被隐式提交（Spec 11 §3 并发保护需要显式事务边界）。
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_database() -> None:
    """数据库连通性检查；不可用时抛出原始异常，由调用方决定语义。"""
    engine = get_engine()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def dispose_engine() -> None:
    """释放连接池（应用关闭时调用）。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("database_engine_disposed")
    _engine = None
    _session_factory = None


def reset_engine() -> None:
    """丢弃缓存的 engine（测试用，不关闭连接）。"""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


__all__ = [
    "Session",
    "check_database",
    "dispose_engine",
    "get_db",
    "get_engine",
    "get_session_factory",
    "reset_engine",
]
