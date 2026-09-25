/**
 * API 错误类型。
 *
 * 每一种都有确定的**处理路径**，不是"报错抛出去让上层随便处理"：
 * - `UnauthorizedError`  → 尝试刷新令牌，失败则退出登录（FE-04 §3）
 * - `ForbiddenError`     → 展示无权限，绝不当成登录失效（FE-04 §4）
 * - `ApiError`           → 其余按业务码提示
 */

/** 后端冻结错误码（`app/core/error_codes.py`）。 */
export const ErrorCode = {
  SUCCESS: 0,
  PERMISSION_DENIED: 403001,
  BAD_REQUEST: 400001,
  UNAUTHENTICATED: 401001,
  MFA_CHALLENGE_INVALID: 401002,
  MFA_CODE_REJECTED: 401003,
  VALIDATION_ERROR: 422001,
  NOT_FOUND: 404001,
  METHOD_NOT_ALLOWED: 405001,
  CONFLICT: 409001,
  PAYLOAD_TOO_LARGE: 413001,
  UNSUPPORTED_MEDIA_TYPE: 415001,
  TOO_MANY_REQUESTS: 429001,
  INTERNAL_ERROR: 500000,
  SERVICE_UNAVAILABLE: 503001,
} as const

export type ErrorCodeValue = (typeof ErrorCode)[keyof typeof ErrorCode]

export class ApiError extends Error {
  readonly code: number
  readonly status: number
  readonly details: unknown

  constructor(code: number, message: string, status = 0, details: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

/** HTTP 401 / code 401001。调用方应触发刷新，刷新失败则退出登录。 */
export class UnauthorizedError extends ApiError {
  constructor(code: number, message: string, status: number, details: unknown = null) {
    super(code, message, status, details)
    this.name = 'UnauthorizedError'
  }
}

/** HTTP 403 / code 403001。权限不足，与"登录失效"是两回事。 */
export class ForbiddenError extends ApiError {
  constructor(code: number, message: string, status: number, details: unknown = null) {
    super(code, message, status, details)
    this.name = 'ForbiddenError'
  }
}

/** 网络层失败（超时、DNS、CORS、fetch 抛错）——不是后端给出的业务码。 */
export class NetworkError extends ApiError {
  // `override`：基类的 `Error.cause` 是标准属性，参数属性会覆盖它，
  // 在 `noImplicitOverride` 下必须显式声明。
  constructor(message: string, override readonly cause: unknown = null) {
    super(-1, message, 0)
    this.name = 'NetworkError'
  }
}
