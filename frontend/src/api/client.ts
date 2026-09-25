import type { ApiEnvelope } from '@/types/common'
import type { TokenPair } from '@/types/auth'
import { ApiError, ErrorCode, ForbiddenError, NetworkError, UnauthorizedError } from './errors'

/**
 * HTTP Client（FE-10 §1）。
 *
 * 统一负责：Base URL、Authorization、X-Trace-ID / X-Request-ID、
 * Response Envelope 解包、错误归一化、401 刷新与重试、403 区分。
 *
 * 这里是**唯一**处理令牌刷新的地方。视图与 store 都不感知 refresh
 * （FE-01 §3："View 不得重复实现认证、权限和 API 错误处理"）。
 */

export type QueryValue = string | number | boolean | null | undefined

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  /**
   * 查询参数；`undefined` / `null` / 空串一律不拼进 URL。
   *
   * 类型是 `object` 而不是 `Record<string, QueryValue>`：各 endpoint 定义的
   * 是 interface，而 TS 只给**类型别名**（type 声明的对象字面量）隐式索引签名，
   * interface 赋给 `Record<...>` 会报"Index signature for type 'string' is missing"。
   * 收窄到 `object` 既能接受 interface，也不至于失去调用点上的字段名检查。
   */
  query?: object
  /** JSON 请求体。 */
  body?: unknown
  /** 需要 Bearer 令牌的请求（默认需要）。 */
  auth?: boolean
  signal?: AbortSignal
  /**
   * 遇到 401 时是否允许刷新令牌后重试，**默认允许**。
   *
   * 只有**会话级别**的接口要关掉它：`/auth/refresh` 自己返回 401 时，
   * 再触发一次刷新就是"刷新请求去刷新自己"，会无限递归（实测直接把
   * 测试跑超时）。同理 `/auth/login`、`/auth/logout` 也不该进入刷新分支。
   */
  refreshOnUnauthorized?: boolean
}

/**
 * 令牌桥。由 `authStore` 注入，避免 api ↔ store 循环依赖。
 * 用回调而不是直接 import store：store 里 import api 又反过来用，
 * 会在 ESM 下形成循环，且让单测必须构造完整 Pinia 实例。
 */
export interface AuthBridge {
  getAccessToken: () => string | null
  getRefreshToken: () => string | null
  /** 用 Refresh Token 换新的令牌对（后端每次都会轮换）。 */
  refresh: (refreshToken: string) => Promise<TokenPair>
  /** 刷新失败（令牌失效 / 会话被撤销）时的收尾：清状态 + 回登录页。 */
  onSessionLost: (reason: SessionLostReason) => void
}

export type SessionLostReason = 'refresh_failed' | 'logout'

export interface ClientConfig {
  baseUrl: string
  bridge: AuthBridge
}

let config: ClientConfig | null = null

export function configureClient(next: ClientConfig): void {
  config = next
}

function currentConfig(): ClientConfig {
  // 显式报错而不是用默认值蒙混：配置缺失意味着"带上了错误的 Base URL"，
  // 那比启动失败更难排查。
  if (config === null) {
    throw new ApiError(-2, 'HTTP client is not configured', 0)
  }
  return config
}

// ------------------------------------------------------------ Trace / Request ID

let seq = 0

/**
 * 生成一个请求标识。
 *
 * 不依赖 `crypto.randomUUID`（jsdom 旧版本没有），但**用**它当首选，
 * 因为 UUID 在日志关联里可读性与去重都更好。
 */
export function nextRequestId(): string {
  const webCrypto = globalThis.crypto
  if (typeof webCrypto?.randomUUID === 'function') {
    return webCrypto.randomUUID()
  }
  seq += 1
  const stamp = Date.now().toString(36)
  return `r-${stamp}-${seq.toString(36)}`
}

// ------------------------------------------------------------ 内部工具

function buildUrl(baseUrl: string, path: string, query: object | undefined): string {
  const normalizedBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  let url = `${normalizedBase}${normalizedPath}`
  if (query && Object.keys(query).length > 0) {
    const pairs: string[] = []
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === '') continue
      pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    }
    if (pairs.length > 0) {
      url = `${url}?${pairs.join('&')}`
    }
  }
  return url
}

/** Envelope 解包：code !== 0 一律视为失败（FE-10 §3）。 */
function unwrap<T>(envelope: ApiEnvelope<T> | null, status: number): T {
  if (envelope === null) {
    // 后端某些端点（如 204 / 纯 JSONResponse）不返回信封。
    // 此时按"成功但无数据"处理，而不是当成解析失败。
    return undefined as T
  }
  if (envelope.code !== ErrorCode.SUCCESS) {
    if (envelope.code === ErrorCode.PERMISSION_DENIED || status === 403) {
      throw new ForbiddenError(envelope.code, envelope.message, status, envelope.data)
    }
    if (status === 401 || envelope.code === ErrorCode.UNAUTHENTICATED) {
      throw new UnauthorizedError(envelope.code, envelope.message, status, envelope.data)
    }
    throw new ApiError(envelope.code, envelope.message, status, envelope.data)
  }
  return envelope.data as T
}

async function parseEnvelope(response: Response): Promise<ApiEnvelope<unknown> | null> {
  if (response.status === 204) return null
  const text = await response.text()
  if (text.length === 0) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    // 非 JSON 响应体（例如网关的 HTML 错误页）。生产环境不应出现，
    // 但一旦出现，把它包装成网络错误比把 JSON.parse 的原始异常抛出去更有用。
    throw new NetworkError(`响应不是 JSON（HTTP ${response.status}）`, text.slice(0, 200))
  }
  if (parsed === null || typeof parsed !== 'object') return parsed as ApiEnvelope<unknown>
  const record = parsed as Record<string, unknown>
  if (typeof record['code'] !== 'number' || typeof record['message'] !== 'string') {
    // 没有信封形状的响应（例如 FastAPI 自己的 422 校验错误）。
    // 保留它，让上层能取到 validation details。
    return { code: ErrorCode.INTERNAL_ERROR, message: String(record['detail'] ?? 'unexpected response'), data: parsed } as ApiEnvelope<unknown>
  }
  return parsed as ApiEnvelope<unknown>
}

// ------------------------------------------------------------ 核心请求

let refreshing: Promise<TokenPair> | null = null

/** 当前是否已有刷新在飞（用于单实例刷新，防止并发请求重复刷新）。 */
export function hasRefreshInFlight(): boolean {
  return refreshing !== null
}

function resetRefreshSlot(): void {
  refreshing = null
}

async function doRefresh(): Promise<TokenPair> {
  const { bridge } = currentConfig()
  const refreshToken = bridge.getRefreshToken()
  if (refreshToken === null || refreshToken === '') {
    throw new UnauthorizedError(ErrorCode.UNAUTHENTICATED, 'no refresh token', 401)
  }
  return bridge.refresh(refreshToken)
}

/** 通知调用方会话已失效（清状态 + 回登录页，FE-04 §5）。 */
let sessionLostNotified = false

/**
 * 通知调用方会话已失效（清状态 + 回登录页，FE-04 §5）。
 *
 * **幂等**：一次"会话失效"只通知一次。并发请求的失败常常是同一件事被观察到
 * 多次 —— 例如三个请求同时 401，刷新成功后三个重试又都 401，此时它们走出的是
 * 同一条"会话确实没了"的结论。如果逐个通知，store 会被清空三遍、router 会被
 * replace 三遍，而调用方（authStore）根本无从判断"到底发生了几件事"。
 * 下一次真正开始刷新时重新开启通知（见下方 `refreshing` 的赋值处）。
 */
function notifySessionLost(): void {
  if (sessionLostNotified) return
  sessionLostNotified = true
  const { bridge } = currentConfig()
  bridge.onSessionLost('refresh_failed')
}

async function requestOnce<T>(path: string, options: RequestOptions): Promise<T> {
  const { baseUrl, bridge } = currentConfig()
  const method = options.method ?? 'GET'
  const url = buildUrl(baseUrl, path, options.query)
  const requestId = nextRequestId()

  const headers: Record<string, string> = {
    Accept: 'application/json',
    // FE-10 §2：每个请求都带这两个关联 ID，后端日志据此串成一条链路。
    'X-Request-ID': requestId,
    'X-Trace-ID': requestId,
  }
  if (options.auth !== false) {
    const token = bridge.getAccessToken()
    if (token !== null && token !== '') {
      headers['Authorization'] = `Bearer ${token}`
    }
  }
  let payload: string | undefined
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(options.body)
  }

  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers,
      body: payload,
      signal: options.signal,
      credentials: 'same-origin',
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new NetworkError('网络请求失败', error)
  }

  const envelope = await parseEnvelope(response)
  return unwrap<T>(envelope as ApiEnvelope<T> | null, response.status)
}

/** 401 之后的重试次数：1 次（刷新后仍 401 说明会话确实失效，再刷没有意义）。 */
const MAX_REFRESH_RETRY = 1

/**
 * 发起请求，处理 401 → 单实例刷新 → 重试。
 *
 * 只重试**一次**：刷新后仍然 401 说明令牌或会话确实失效了，再刷没有意义
 * （而且会制造一次可被滥用的刷新风暴）。
 *
 * `retriesLeft` 必须显式带在递归里。最初的版本把"重试"直接写在 `request` 的
 * catch 里，于是**重试得到的 401 会再次进入同一个 catch**，刷新槽位此时已释放，
 * 于是又刷一次、又重试一次…… 形成无限刷新循环：刷新接口一旦短时抖动，
 * 前端会不停打 `/auth/refresh`，把一次网络抖动放大成刷新风暴。
 * 这是靠单元测试（"刷新后仍 401：fetch 调用次数有上界"）才暴露出来的。
 */
async function requestWithRefresh<T>(
  path: string,
  options: RequestOptions,
  retriesLeft: number,
): Promise<T> {
  try {
    return await requestOnce<T>(path, options)
  } catch (error) {
    if (!(error instanceof UnauthorizedError)) throw error

    // 会话级接口（`/auth/refresh` 等）与"已重试过"两种情况都不再刷新：
    // 前者会刷新自己，后者刷新过一次就够了。
    if (options.refreshOnUnauthorized === false || retriesLeft <= 0) {
      // 重试仍被拒：令牌刚换过就还是 401，说明会话本身已经不成立了
      // （FE-04 §3 的"刷新失败 Logout"包含这种：继续留在页面上只会到处 401）。
      if (retriesLeft <= 0) notifySessionLost()
      throw error
    }

    if (refreshing === null) {
      // 一次新的刷新尝试 = 一个新的"会话失效"判定周期，重新开启通知。
      sessionLostNotified = false
      refreshing = doRefresh()
        .then((pair) => {
          resetRefreshSlot()
          return pair
        })
        .catch((reason: unknown) => {
          resetRefreshSlot()
          notifySessionLost()
          throw reason instanceof UnauthorizedError
            ? reason
            : new UnauthorizedError(ErrorCode.UNAUTHENTICATED, 'session expired', 401)
        })
    }

    // 新令牌由 `refresh` 回调写回 store，这里不用处理。
    await refreshing
    return await requestWithRefresh<T>(path, { ...options }, retriesLeft - 1)
  }
}

export function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return requestWithRefresh<T>(path, options, MAX_REFRESH_RETRY)
}

/** 便捷方法。 */
export const http = {
  get: <T>(path: string, query?: object, init?: RequestOptions): Promise<T> =>
    request<T>(path, { ...init, method: 'GET', query }),
  post: <T>(path: string, body?: unknown, init?: RequestOptions): Promise<T> =>
    request<T>(path, { ...init, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, init?: RequestOptions): Promise<T> =>
    request<T>(path, { ...init, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, init?: RequestOptions): Promise<T> =>
    request<T>(path, { ...init, method: 'PATCH', body }),
  delete: <T>(path: string, init?: RequestOptions): Promise<T> =>
    request<T>(path, { ...init, method: 'DELETE' }),
}
