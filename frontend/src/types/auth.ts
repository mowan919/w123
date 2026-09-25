import type { DateTime, ID } from './common'

/** `POST /auth/login` 请求体。口令不落任何前端持久化介质（FE-11 §2）。 */
export interface LoginRequest {
  username: string
  password: string
}

/** `POST /auth/refresh` 请求体。Refresh Token 每次调用都会轮换。 */
export interface RefreshRequest {
  refresh_token: string
}

/** `POST /auth/password` 请求体。 */
export interface ChangePasswordRequest {
  current_password: string
  new_password: string
}

/** 令牌对（登录 / 刷新共用）。 */
export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: 'Bearer'
  access_expires_at: DateTime
  refresh_expires_at: DateTime
}

/** `POST /auth/login` 成功响应。 */
export interface LoginResponse extends TokenPair {
  must_change_password: boolean
  user: AuthUser
}

/** MFA 是**挑战令牌**而非会话令牌，形状与 TokenPair 不同。 */
export interface LoginMfaRequiredResponse {
  mfa_required: boolean
  mfa_token: string
  expires_at: DateTime
  provider: string
}

export interface AuthUser {
  id: ID
  username: string
  display_name: string
}

/** `POST /auth/logout` 响应。重复登出不是错误，是幂等事实。 */
export interface LogoutResponse {
  revoked: boolean
  already_revoked: boolean
}

/** `GET /auth/me` 响应。注意：这里**没有** password 相关字段。 */
export interface MeResponse {
  id: ID
  username: string
  display_name: string
  department_id: ID | null
  status: 'ACTIVE' | 'DISABLED' | 'LOCKED'
  must_change_password: boolean
  password_expired: boolean
}

/** `POST /auth/mfa/verify` 成功后的令牌对。 */
export type MfaVerifyResponse = TokenPair

/** `POST /auth/mfa/verify` 请求体（`app.schemas.mfa.MfaCodeRequest`）。 */
export interface MfaCodeRequest {
  code: string
}

/** `POST /auth/mfa/verify` 请求体（`app.schemas.mfa.MfaVerifyRequest`）。 */
export interface MfaVerifyRequest {
  mfa_token: string
  code: string
}

/** `POST /auth/mfa/setup` 响应。 */
export interface MfaSetupResponse {
  provider: string
  /** 该值只在首次绑定时返回一次；禁止写入日志（FE-11 §2）。 */
  secret: string
  provisioning_uri: string
  status: 'DISABLED' | 'SETUP' | 'ENABLED'
}

/** `POST /auth/mfa/enable` / `disable` 响应。 */
export interface MfaActionResponse {
  provider: string
  status: 'DISABLED' | 'SETUP' | 'ENABLED'
  secret_cleared: boolean
}

/** `GET /auth/mfa` 响应。 */
export interface MfaStatusResponse {
  provider: string | null
  status: 'DISABLED' | 'SETUP' | 'ENABLED'
  has_credential: boolean
  setup_at: DateTime | null
  enabled_at: DateTime | null
  verified_at: DateTime | null
  /** 是否强制启用（来自系统参数 `mfa.required_default`）。 */
  required: boolean
  source: string
}
