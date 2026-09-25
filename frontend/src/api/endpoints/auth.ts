import { http } from '../client'
import type {
  ChangePasswordRequest,
  LoginRequest,
  LoginResponse,
  LoginMfaRequiredResponse,
  LogoutResponse,
  MeResponse,
  MfaActionResponse,
  MfaCodeRequest,
  MfaSetupResponse,
  MfaStatusResponse,
  MfaVerifyRequest,
  RefreshRequest,
  TokenPair,
} from '@/types/auth'

/** 认证相关端点（`08 §3`）。 */

/** 登录。口令为**明文口令**，不入库、不落日志（FE-11 §2）。 */
export function login(payload: LoginRequest): Promise<LoginResponse | LoginMfaRequiredResponse> {
  return http.post<LoginResponse | LoginMfaRequiredResponse>('/auth/login', payload)
}

/** 提交动态码完成 MFA 挑战。 */
export function verifyMfa(payload: MfaVerifyRequest): Promise<TokenPair> {
  return http.post<TokenPair>('/auth/mfa/verify', payload)
}

/**
 * 用 Refresh Token 换新令牌对（轮换）。
 *
 * `refreshOnUnauthorized: false` 是必须的：刷新请求自己返回 401 时，
 * 若再走一次 401→刷新分支，就是"刷新请求去刷新自己"的无限递归。
 */
export function refresh(payload: RefreshRequest): Promise<TokenPair> {
  return http.post<TokenPair>('/auth/refresh', payload, { refreshOnUnauthorized: false })
}

/** 登出；重复登出不报错。 */
export function logout(): Promise<LogoutResponse> {
  return http.post<LogoutResponse>('/auth/logout')
}

export function getMe(): Promise<MeResponse> {
  return http.get<MeResponse>('/auth/me')
}

/** 本人改密 / 解除强制改密。 */
export function changePassword(payload: ChangePasswordRequest): Promise<void> {
  return http.post<void>('/auth/password', payload)
}

export function getMfaStatus(): Promise<MfaStatusResponse> {
  return http.get<MfaStatusResponse>('/auth/mfa')
}

/** 取绑定信息；`secret` 只在一次之内有效，禁止落日志。 */
export function setupMfa(): Promise<MfaSetupResponse> {
  return http.post<MfaSetupResponse>('/auth/mfa/setup')
}

export function enableMfa(payload: MfaCodeRequest): Promise<MfaActionResponse> {
  return http.post<MfaActionResponse>('/auth/mfa/enable', payload)
}

export function disableMfa(payload: MfaCodeRequest): Promise<MfaActionResponse> {
  return http.post<MfaActionResponse>('/auth/mfa/disable', payload)
}
