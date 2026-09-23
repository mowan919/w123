"""Redis 异步基础设施。

Spec 11 §1：Redis 用于 Session 辅助状态、权限缓存、permission version、
rate limit 及其他短期缓存。

**本阶段边界**：
- 只建立连接与连通性检查；
- **不定义任何 Redis Key 命名结构** —— Redis Key 精确命名属于
  UNRESOLVED DESIGN DECISION（Spec 11 §1「具体 Key 命名规范在技术实现阶段冻结」、
  Spec 16 §34 第 3 项）。Phase 2 起再冻结。
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Redis | None = None


def get_redis() -> Redis:
    """返回进程级 Redis 客户端（惰性初始化）。

    注意：构造客户端不会建立连接，实际连接在首次命令时发生。
    """
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=settings.redis_socket_timeout,
            socket_connect_timeout=settings.redis_socket_timeout,
            health_check_interval=30,
        )
        logger.info("redis_client_created url=%s", settings.redis_url_safe)
    return _client


async def check_redis() -> None:
    """Redis 连通性检查；不可用时抛出原始异常，由调用方决定语义。"""
    client = get_redis()
    await client.ping()


async def close_redis() -> None:
    """关闭 Redis 连接（应用关闭时调用）。"""
    global _client
    if _client is not None:
        await _client.aclose()
        logger.info("redis_client_closed")
    _client = None


def reset_redis() -> None:
    """丢弃缓存的客户端（测试用，不关闭连接）。"""
    global _client
    _client = None


__all__ = ["check_redis", "close_redis", "get_redis", "reset_redis"]
