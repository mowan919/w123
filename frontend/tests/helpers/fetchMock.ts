/**
 * 假 fetch。
 *
 * 不依赖 `globalThis.Response` —— vitest 的 jsdom 环境不保证提供它，
 * 而 `requestOnce` 只用到 `status` 与 `text()` 两处，自己造一个最小对象
 * 比"猜运行时到底有没有 Response"更稳。
 */

export type FetchCall = { url: string; init: RequestInit }

export interface StubFetch {
  calls: FetchCall[]
  /** 重置计数（每次请求 `assert` 前都会重新数，否则断言会被历史调用污染）。 */
  reset: () => void
}

export interface FakeResponseInit {
  status?: number
  /** 原始响应体；默认按 JSON 序列化。传 `null` 表示 204 / 空响应。 */
  body?: unknown
  /** 强制一个非 JSON 的响应体（用于"网关返回 HTML"这类分支）。 */
  rawText?: string
}

/**
 * 造一个响应。
 *
 * 不需要覆盖 `Response` 的全部接口 —— client 只读 `status` 和 `text()`。
 */
export function fakeResponse(status: number, body?: unknown, rawText?: string): Response {
  const text = rawText ?? (body === undefined || body === null ? '' : JSON.stringify(body))
  return {
    status,
    text: async () => text,
    json: async () => JSON.parse(text) as unknown,
  } as Response
}

/** 业务成功（Envelope `code === 0`）。 */
export function ok<T>(data: T, status = 200): Response {
  return fakeResponse(status, { code: 0, message: 'success', data })
}

/**
 * 业务失败（Envelope `code !== 0`）。
 *
 * 后端失败响应的形状是 `{ code, message, data: null }`。
 */
export function fail(code: number, message: string, status = 400): Response {
  return fakeResponse(status, { code, message, data: null })
}

/** 401 —— 唯一会触发刷新与重试的状态。 */
export function unauthorized(message = 'token expired'): Response {
  return fail(401001, message, 401)
}

/** 403 —— 权限拒绝，**不该**触发刷新。 */
export function forbidden(message = 'permission denied'): Response {
  return fail(403001, message, 403)
}

/**
 * 敲一个假 fetch。
 *
 * `handler` 每次调用都会被调用，用闭包里的计数器做"第几次返回什么"的
 * 序列控制（401→刷新→重试 正是靠这个串起来的）。
 */
export function stubFetch(handler: (call: FetchCall, nth: number) => Promise<Response>): StubFetch {
  const calls: FetchCall[] = []
  const stub: StubFetch = { calls, reset: () => (calls.length = 0) }
  vi.stubGlobal(
    'fetch',
    async (url: string, init: RequestInit): Promise<Response> => {
      const call: FetchCall = { url, init }
      calls.push(call)
      return handler(call, calls.length)
    },
  )
  return stub
}

/** 记录全部请求 URL 的简写：多数用例只关心"发了什么"。 */
export function urlOf(calls: FetchCall[]): string[] {
  return calls.map((call) => call.url)
}

/**
 * 从请求头里取某个值。
 *
 * `RequestInit.headers` 在传入对象是保持原样的，所以这里按对象读，
 * 但仍容忍被运行时规范化成数组的情况。
 */
export function headerOf(call: FetchCall, name: string): string | undefined {
  const headers = call.init.headers
  if (headers === undefined) return undefined
  if (typeof headers === 'string') return undefined
  if (Array.isArray(headers)) {
    for (const [key, value] of headers) {
      if (String(key).toLowerCase() === name.toLowerCase()) return String(value)
    }
    return undefined
  }
  const record = headers as Record<string, string>
  const key = Object.keys(record).find((item) => item.toLowerCase() === name.toLowerCase())
  return key === undefined ? undefined : record[key]
}
