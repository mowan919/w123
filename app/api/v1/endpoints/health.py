"""健康检查端点。

Spec 13 §4 Health：至少提供 application health、database health、redis health。

设计约定：
- liveness（`/health`）**不依赖**任何外部组件，用于判断进程是否存活；
- readiness（`/health/ready`）聚合 database 与 redis 状态；
- 失败响应严格遵循 Spec 08 §2 冻结格式（`data` 为 null），
  因此**不在响应体中回显** DSN、异常消息等内部细节（Spec 10 §9）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import app as app_package
from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.response import error_response, success_response
from app.db.redis import check_redis
from app.db.session import check_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])

PROBE_TIMEOUT_SECONDS = 3.0


async def _probe(check: Callable[[], Awaitable[None]]) -> tuple[bool, str | None]:
    """执行连通性探测。

    Returns:
        (是否可用, 失败原因)。失败原因只返回异常类型名，
        绝不返回异常消息（可能包含 DSN 等内部信息）。
    """
    try:
        await asyncio.wait_for(check(), timeout=PROBE_TIMEOUT_SECONDS)
    except TimeoutError:
        return False, "timeout"
    except Exception as exc:
        logger.warning("health_probe_failed check=%s error=%s", check.__name__, type(exc).__name__)
        return False, type(exc).__name__
    return True, None


@router.get("/health", summary="应用存活检查")
async def liveness() -> JSONResponse:
    """Liveness 探针：仅反映进程状态，不探测外部依赖。"""
    return success_response(
        {
            "status": "ok",
            "app": settings.app_name,
            "env": settings.app_env,
            "version": app_package.__version__,
        }
    )


@router.get("/health/ready", summary="就绪检查（database + redis）")
async def readiness() -> JSONResponse:
    """Readiness 探针：database 与 redis 全部可用才返回成功。"""
    db_ok, db_error = await _probe(check_database)
    redis_ok, redis_error = await _probe(check_redis)

    if db_ok and redis_ok:
        return success_response(
            {
                "status": "ready",
                "checks": {
                    "database": {"status": "up"},
                    "redis": {"status": "up"},
                },
            }
        )

    down: list[str] = []
    if not db_ok:
        down.append("database")
    if not redis_ok:
        down.append("redis")

    logger.error("readiness_failed down=%s db_error=%s redis_error=%s", down, db_error, redis_error)

    # Spec 08 §2：失败响应 data 必须为 null
    return error_response(
        ErrorCode.SERVICE_UNAVAILABLE,
        message=f"service unavailable: {', '.join(down)} down",
        http_status=503,
    )


async def _component_health(name: str, check: Callable[[], Awaitable[None]]) -> JSONResponse:
    ok, _ = await _probe(check)
    if ok:
        return success_response({"component": name, "status": "up"})
    return error_response(
        ErrorCode.SERVICE_UNAVAILABLE,
        message=f"{name} unavailable",
        http_status=503,
    )


@router.get("/health/db", summary="数据库健康检查")
async def database_health() -> JSONResponse:
    return await _component_health("database", check_database)


@router.get("/health/redis", summary="Redis 健康检查")
async def redis_health() -> JSONResponse:
    return await _component_health("redis", check_redis)


__all__: list[Any] = ["router"]
