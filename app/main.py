"""FastAPI 应用装配。

Spec 08 §1 Base：所有业务 API 位于 `/api/v1/admin`。
Spec 08 §3：认证端点位于 `/api/v1/auth`（DD-02 阶段裁定，见决策台账）。
Spec 06 §3：Trace 中间件必须覆盖所有请求。
Spec 13 §5：结构化、带 trace_id / request_id、脱敏的日志。

两个前缀的分工
-------------
- `/api/v1/admin/**`：**管理员资源**域。调用者必须已经是"已认证的操作者"。
- `/api/v1/auth/**`：**认证**域。登录时尚不存在操作者身份，
  因此不能放在 admin 域下（否则语义上要求"先认证才能登录"）。

Phase 4 边界：业务资源端点（users / roles / departments / sessions /
audit / dicts ...）分别属于后续 Phase，本阶段只交付认证域。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.dicts import public_router as public_dict_router
from app.api.v1.endpoints.mfa import router as mfa_router
from app.api.v1.router import api_router
from app.audit.buffer import flush_logs
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.response import success_response
from app.db.redis import check_redis, close_redis
from app.db.session import check_database, dispose_engine
from app.middleware.security_headers import SecurityHeadersMiddleware
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
        # 关闭前落库一次：启动 / 关闭期间产生的日志落在"兜底缓冲"里，
        # 若不在进程结束前写出，它们会随进程一起消失 ——
        # 而"服务为什么重启"这类问题的答案往往正好在那几行里。
        # 必须在 `dispose_engine()` **之前**调用：落库需要一个可用引擎。
        # `flush_logs()` 不抛异常且有 5 秒上限，因此不会拖住关闭流程。
        await flush_logs()
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
    # 安全响应头：最后 add 的中间件**最外层**，因此它看到的
    # `http.response.start` 是最终发出的那一版 —— 包括 TraceMiddleware
    # 补的 trace/request id。顺序反了也不会出错（各自补缺），
    # 但保持"外层做全局属性"更符合直觉。
    application.add_middleware(SecurityHeadersMiddleware)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    # 认证域独立前缀：登录时尚不存在"操作者"，不属于 admin 资源域。
    application.include_router(auth_router, prefix=settings.auth_v1_prefix)
    # MFA 自我管理端点（`/auth/mfa*`）同样是认证域
    # —— 它们操作的是"我自己的二次验证"，不需要 admin 资源域的数据范围语义。
    # `POST /auth/mfa/verify` 例外地挂在 auth_router 里（它是登录流程的续完），
    # 理由见 `app/api/v1/endpoints/mfa.py` 的模块文档。
    application.include_router(mfa_router, prefix=settings.auth_v1_prefix)
    # 公开字典查询（Phase 7 / Spec `05 §4`）：路径是 `/api/v1/dicts/{dictCode}`，
    # **不在** admin 域下，因此单独以 public 前缀挂载。
    # 注意"公开"不等于"匿名"：端点仍要求已认证（JUDGMENT-7-03，
    # 理由见 `app/api/v1/endpoints/dicts.py` 的模块文档）。
    application.include_router(public_dict_router, prefix=settings.public_v1_prefix)

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
