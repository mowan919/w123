"""全局异常处理。

Spec 10 §9：统一异常处理，生产环境不得泄漏 stack trace、SQL、Secret、内部路径。
Spec 08 §2：失败响应形如 {"code": 403001, "message": "...", "data": null}。

设计：
- `AppError` 及其子类表达"可以安全返回给调用方"的受控错误；
- 未被捕获的异常统一转为 500000，响应体**不含任何**内部细节，
  完整堆栈只写入服务端日志（携带 trace_id / request_id）。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.error_codes import ErrorCode
from app.core.response import error_response

logger = logging.getLogger(__name__)

# INTERIM（DD-12 未冻结）：HTTP 状态码 → 业务错误码的临时映射。
_HTTP_STATUS_TO_CODE: dict[int, int] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.PERMISSION_DENIED,
    403: ErrorCode.PERMISSION_DENIED,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    415: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.TOO_MANY_REQUESTS,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


class AppError(Exception):
    """受控应用异常基类。

    只有本类及其子类的 message 会被返回给调用方。
    """

    code: int = int(ErrorCode.INTERNAL_ERROR)
    http_status: int = 500
    message: str = "internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        data: Any = None,
        http_status: int | None = None,
        code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.data = data
        if http_status is not None:
            self.http_status = http_status
        if code is not None:
            self.code = code
        super().__init__(self.message)

    def to_response(self) -> JSONResponse:
        return error_response(
            self.code,
            message=self.message,
            http_status=self.http_status,
            data=self.data,
        )


class BadRequestError(AppError):
    code = int(ErrorCode.BAD_REQUEST)
    http_status = 400
    message = "bad request"


class NotFoundError(AppError):
    code = int(ErrorCode.NOT_FOUND)
    http_status = 404
    message = "resource not found"


class PermissionDeniedError(AppError):
    """Spec 08 §2 冻结示例：403001 / permission denied。"""

    code = int(ErrorCode.PERMISSION_DENIED)
    http_status = 403
    message = "permission denied"


class ConflictError(AppError):
    code = int(ErrorCode.CONFLICT)
    http_status = 409
    message = "conflict"


class DependencyUnavailableError(AppError):
    """依赖（PostgreSQL / Redis）不可用。"""

    code = int(ErrorCode.SERVICE_UNAVAILABLE)
    http_status = 503
    message = "service unavailable"


class InternalError(AppError):
    code = int(ErrorCode.INTERNAL_ERROR)
    http_status = 500
    message = "internal server error"


def _sanitize_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """提取校验错误，且**丢弃 input 原文**。

    FastAPI 默认 422 响应会回显用户输入（`input` 字段）。
    在登录/改密等场景下该字段可能包含明文密码，
    Spec 10 §4 明确要求不得泄漏 password / MFA secret / token 明文，
    因此这里只保留 loc / msg / type。
    """
    sanitized: list[dict[str, Any]] = []
    for err in exc.errors():
        sanitized.append(
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "msg": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
        )
    return sanitized


async def handle_app_error(_request, exc: AppError):  # type: ignore[no-untyped-def]
    logger.warning(
        "app_error code=%s status=%s message=%s",
        exc.code,
        exc.http_status,
        exc.message,
    )
    return exc.to_response()


async def handle_validation_error(_request, exc: RequestValidationError):  # type: ignore[no-untyped-def]
    logger.info("validation_error errors=%s", len(exc.errors()))
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        http_status=422,
        data=_sanitize_validation_errors(exc),
    )


async def handle_http_exception(_request, exc: StarletteHTTPException):  # type: ignore[no-untyped-def]
    code = _HTTP_STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    detail = exc.detail if isinstance(exc.detail, str) else None
    return error_response(
        code,
        message=detail,
        http_status=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


async def handle_unexpected_error(_request, exc: Exception):  # type: ignore[no-untyped-def]
    """兜底：绝不把内部异常细节返回给调用方（Spec 10 §9）。"""
    logger.exception("unhandled_exception type=%s", type(exc).__name__)
    return error_response(ErrorCode.INTERNAL_ERROR, http_status=500)


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。"""
    app.add_exception_handler(AppError, handle_app_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, handle_unexpected_error)
