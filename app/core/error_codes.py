"""错误码定义。

Frozen 部分（不可修改）
-----------------------
Spec 08 §2 Response：
    成功  {"code": 0, "message": "success", "data": {}}
    失败  {"code": 403001, "message": "permission denied", "data": null}
`0` 与 `403001` 直接来自 Spec，属于冻结内容。

UNRESOLVED DESIGN DECISION —— DD-12
-----------------------------------
Spec 未定义错误码段位分配表（业务域占用哪些号段、长度规则、与 HTTP 状态码
映射关系、message 语种等）。因此下方标记为 `INTERIM` 的常量属于
**临时技术默认值**，仅为让 Phase 1 的 Envelope 与异常处理可运行。

处理方式（遵循 Spec 14 §5 / CODING_PROTOCOL §3）：
- 不把临时默认值当作最终需求；
- 全部集中在本文件，便于 DD-12 冻结后一次性替换；
- 已在 Phase 1 报告中登记为 UNRESOLVED DESIGN DECISION。

这些 INTERIM 码都是**协议层/基础设施层**语义，不表达任何业务规则。
"""

from __future__ import annotations

from enum import IntEnum


class ErrorCode(IntEnum):
    """API 响应 code。"""

    # ---- Frozen: Spec 08 §2 ----
    SUCCESS = 0
    PERMISSION_DENIED = 403001

    # ---- INTERIM (DD-12 未冻结，临时代码) ----
    BAD_REQUEST = 400001
    #: 未认证 / 令牌无效或过期（Phase 4 新增）。
    #: DD-12 未冻结 401 段位，此处取 "HTTP 401 + 序号 001" 的既有推导惯例。
    UNAUTHENTICATED = 401001
    VALIDATION_ERROR = 422001
    NOT_FOUND = 404001
    METHOD_NOT_ALLOWED = 405001
    CONFLICT = 409001
    PAYLOAD_TOO_LARGE = 413001
    UNSUPPORTED_MEDIA_TYPE = 415001
    TOO_MANY_REQUESTS = 429001
    INTERNAL_ERROR = 500000
    SERVICE_UNAVAILABLE = 503001


DEFAULT_MESSAGES: dict[int, str] = {
    ErrorCode.SUCCESS: "success",
    ErrorCode.PERMISSION_DENIED: "permission denied",
    ErrorCode.BAD_REQUEST: "bad request",
    ErrorCode.UNAUTHENTICATED: "unauthenticated",
    ErrorCode.VALIDATION_ERROR: "validation error",
    ErrorCode.NOT_FOUND: "resource not found",
    ErrorCode.METHOD_NOT_ALLOWED: "method not allowed",
    ErrorCode.CONFLICT: "conflict",
    ErrorCode.PAYLOAD_TOO_LARGE: "payload too large",
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: "unsupported media type",
    ErrorCode.TOO_MANY_REQUESTS: "too many requests",
    ErrorCode.INTERNAL_ERROR: "internal server error",
    ErrorCode.SERVICE_UNAVAILABLE: "service unavailable",
}
