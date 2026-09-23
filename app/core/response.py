"""统一 API Response Envelope。

Frozen（Spec 08 §2 / AGENTS.md §10）：
    成功  {"code": 0,    "message": "success",           "data": {}}
    失败  {"code": 403001, "message": "permission denied", "data": null}

本模块只负责"把结果装进信封"，不定义任何业务语义。
错误码来源见 `app.core.error_codes`（其中 INTERIM 部分待 DD-12 冻结后替换）。
"""

from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.error_codes import DEFAULT_MESSAGES, ErrorCode

SUCCESS_CODE = int(ErrorCode.SUCCESS)
SUCCESS_MESSAGE = DEFAULT_MESSAGES[ErrorCode.SUCCESS]


class ApiResponse[T](BaseModel):
    """统一响应模型（用于 OpenAPI 文档与显式返回）。"""

    code: int = Field(default=SUCCESS_CODE, description="业务响应码，0 表示成功")
    message: str = Field(default=SUCCESS_MESSAGE, description="提示信息")
    data: T | None = Field(default=None, description="业务数据；失败时为 null")


def success_response(
    data: Any = None,
    *,
    message: str = SUCCESS_MESSAGE,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """构造成功响应。

    Spec 08 §2：成功时 code = 0、message = "success"。
    """
    payload: dict[str, Any] = {
        "code": SUCCESS_CODE,
        "message": message,
        "data": jsonable_encoder(data) if data is not None else {},
    }
    return JSONResponse(status_code=200, content=payload, headers=headers)


def error_response(
    code: int,
    *,
    message: str | None = None,
    http_status: int = 400,
    data: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """构造失败响应。

    Spec 08 §2：失败时 data 必须为 null。
    """
    payload: dict[str, Any] = {
        "code": int(code),
        "message": message or DEFAULT_MESSAGES.get(int(code), "error"),
        "data": data,
    }
    return JSONResponse(status_code=http_status, content=payload, headers=headers)
