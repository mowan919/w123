"""FastAPI 应用装配。

Spec 08 §1 Base：所有业务 API 位于 `/api/v1/admin`。
Spec 06 §3：Trace 中间件必须覆盖所有请求。
Spec 13 §5：结构化、带 trace_id / request_id、脱敏的日志。

Phase 1 边界：本阶段不实现任何业务模块
（User / Department / Role / Permission / Auth / Session / MFA / Dictionary）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.response import success_response
from app.db.redis import check_redis, close_redis
from app.db.session import check_database, dispose_engine
from app.middleware.trace import TraceMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期。

    启动策略：**fail-soft**。
    外部依赖（PostgreSQL / Redis）不可用时只记录 WARNING 并继续启动，
    以便进程仍能提供 liveness 探针与诊断信息；
    真实可用性由 readiness 探针（`/health/ready`）表达，返回 503。
    这样避免了"依赖抖动导致整个服务反复重启"的常见故障模式。
    """
    configure_logging(settings.log_level, json_output=settings.log_json)
    logger.info(
        "application_starting app=%s version=%s env=%s debug=%s",
        settings.app_name,
        __version__,
        settings.app_env,
        settings.debug,
    )
    logger.info("postgres_target=%s", settings.database_url_safe)
    logger.info("redis_target=%s", settings.redis_url_safe)

    for label, probe in (("database", check_database), ("redis", check_redis)):
        try:
            await probe()
            logger.info("dependency_ready dependency=%s", label)
        except Exception as exc:
            logger.warning(
                "dependency_unavailable dependency=%s error=%s (readiness 将返回 503)",
                label,
                type(exc).__name__,
            )

    try:
        yield
    finally:
        logger.info("application_stopping")
        await dispose_engine()
        await close_redis()


def create_app() -> FastAPI:
    """构造 FastAPI 应用。"""
    application = FastAPI(
        title="VCTN Admin API",
        version=__version__,
        description="VCTN 后台管理平台 API（Phase 1 工程基线）",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    register_exception_handlers(application)
    application.add_middleware(TraceMiddleware)
    application.include_router(api_router, prefix=settings.api_v1_prefix)

    @application.get("/health", include_in_schema=False, tags=["Health"])
    async def root_liveness() -> object:
        """根路径 liveness 别名，供容器 / 负载均衡探针使用。"""
        return success_response(
            {
                "status": "ok",
                "app": settings.app_name,
                "env": settings.app_env,
                "version": __version__,
            }
        )

    return application


app = create_app()
