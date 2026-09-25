import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { configureClient, hasRefreshInFlight, http, nextRequestId, request } from '@/api/client'
import { ApiError, ForbiddenError, NetworkError, UnauthorizedError } from '@/api/errors'
import type { AuthBridge, SessionLostReason } from '@/api/client'
import type { TokenPair } from '@/types'
import { fail, forbidden, headerOf, ok, stubFetch, unauthorized } from '../helpers/fetchMock'
import { makeTokenPair } from '../helpers/fixtures'

/**
 * HTTP Client 与令牌刷新（FE-10 §1 / FE-04 §3 / FE-12 §2）。
 *
 * 这里要钉死的是**令牌刷新的四条语义**，写错任何一条都会在生产上表现为
 * 不好复现的偶发问题：
 *
 * 1. **单实例刷新**：并发的多个 401 只触发一次 refresh（否则会并发刷新把
 *    Refresh Token 轮换成无效）。
 * 2. **只重试一次**：重试得到的 401 不再触发新一轮刷新，调用次数有上界。
 * 3. **刷新失败即登出**（FE-04 §3）。
 * 4. **403 不是登录失效**：权限拒绝不该触发刷新，也不该把人踢下线。
 */

let tokens: { access: string | null; refresh: string | null }
let refreshMock: Mock<(refreshToken: string) => Promise<TokenPair>>
let onSessionLostMock: Mock<(reason: SessionLostReason) => void>

beforeEach(() => {
  tokens = { access: 'access-1', refresh: 'refresh-1' }
  onSessionLostMock = vi.fn()
  // 刷新自己也走一次 HTTP —— 与 `authStore.doRefresh` 同构。
  // 早期版本让桥接层直接返回令牌对，结果"刷新请求"在计数上凭空消失，
  // 若干调用次数的断言就跟着算错了。
  refreshMock = vi.fn(async (refreshToken: string): Promise<TokenPair> => {
    const pair = await http.post<TokenPair>(
      '/auth/refresh',
      { refresh_token: refreshToken },
      { refreshOnUnauthorized: false },
    )
    tokens = { access: pair.access_token, refresh: pair.refresh_token }
    return pair
  })
  const bridge: AuthBridge = {
    getAccessToken: () => tokens.access,
    getRefreshToken: () => tokens.refresh,
    refresh: refreshMock,
    onSessionLost: onSessionLostMock,
  }
  configureClient({ baseUrl: '/api/v1/', bridge })
})

/** 等到条件成立（避免用固定次数的 `Promise.resolve` 猜 microtask 数量）。 */
async function until(condition: () => boolean): Promise<void> {
  for (let i = 0; i < 2000; i += 1) {
    if (condition()) return
    await Promise.resolve()
  }
  throw new Error('条件始终未成立')
}

/**
 * 「每个业务 URL 第一次必被拒、之后放行」的假后端。
 *
 * 写过这一行的用例都栽在同一个坑上：假后端按**第几次调用**返回 401，于是
 * 刷新后的那次重试也被判 401，用例永远走不到"重试成功"的分支，最后表现成
 * "promise rejected instead of resolving"。改成按 URL 判定后语义就清楚了 ——
 * 401 只发生在"这个 URL 的第一次尝试"，重试必然能过。
 */
function rejectFirstPerUrl(): { handler: (call: { url: string }) => Promise<Response> } {
  const seen = new Set<string>()
  return {
    handler: async (call) => {
      if (seen.has(call.url)) return ok({ ok: true })
      seen.add(call.url)
      return unauthorized()
    },
  }
}

describe('请求装配', () => {
  it('baseUrl 末尾斜杠与 path 开头斜杠都会被归一化', async () => {
    const fetchStub = stubFetch(async () => ok({ ok: true }))
    await http.get('/probe')
    expect(fetchStub.calls[0]?.url).toBe('/api/v1/probe')
  })

  it('每个请求都带 X-Request-ID / X-Trace-ID 与 Authorization', async () => {
    const fetchStub = stubFetch(async () => ok({}))
    await http.get('/probe')
    const call = fetchStub.calls[0]
    expect(call).toBeDefined()
    expect(headerOf(call!, 'X-Request-ID')).toBeTruthy()
    expect(headerOf(call!, 'X-Trace-ID')).toBe(headerOf(call!, 'X-Request-ID'))
    expect(headerOf(call!, 'Authorization')).toBe('Bearer access-1')
  })

  it('auth: false 的请求不带 Authorization', async () => {
    const fetchStub = stubFetch(async () => ok({}))
    await request('/auth/login', { method: 'POST', body: { username: 'u' }, auth: false })
    expect(headerOf(fetchStub.calls[0]!, 'Authorization')).toBeUndefined()
  })

  it('空值查询参数不进 URL（undefined / null / 空串）', async () => {
    const fetchStub = stubFetch(async () => ok({}))
    await http.get('/admin/users', { pageNum: 1, pageSize: 20, keyword: '', status: null, id: undefined })
    expect(fetchStub.calls[0]?.url).toBe('/api/v1/admin/users?pageNum=1&pageSize=20')
  })

  it('查询参数按 key / value 分别编码', async () => {
    const fetchStub = stubFetch(async () => ok({}))
    await http.get('/search', { q: 'a b&c' })
    expect(fetchStub.calls[0]?.url).toBe('/api/v1/search?q=a%20b%26c')
  })

  it('请求体以 JSON 序列化并带 Content-Type', async () => {
    const fetchStub = stubFetch(async () => ok({}))
    await http.post('/admin/users', { username: 'u', password: 'p' })
    expect(headerOf(fetchStub.calls[0]!, 'Content-Type')).toBe('application/json')
    expect(fetchStub.calls[0]?.init.body).toBe('{"username":"u","password":"p"}')
  })
})

describe('响应解包', () => {
  it('成功返回 data', async () => {
    stubFetch(async () => ok({ id: '1' }))
    await expect(http.get<{ id: string }>('/x')).resolves.toEqual({ id: '1' })
  })

  it('业务码非 0 抛 ApiError', async () => {
    stubFetch(async () => fail(409001, '冲突'))
    await expect(http.get('/x')).rejects.toBeInstanceOf(ApiError)
    await expect(http.get('/x')).rejects.toMatchObject({ code: 409001, message: '冲突' })
  })

  it('403 + 权限码抛 ForbiddenError', async () => {
    stubFetch(async () => forbidden())
    await expect(http.get('/x')).rejects.toBeInstanceOf(ForbiddenError)
  })

  it('401 抛 UnauthorizedError（刷新与重试在更上层发生）', async () => {
    stubFetch(async () => unauthorized())
    await expect(http.get('/x')).rejects.toBeInstanceOf(UnauthorizedError)
  })

  it('204 / 空响应体按"成功但无数据"处理', async () => {
    stubFetch(async () => ({ status: 204, text: async () => '' } as Response))
    await expect(http.delete('/x')).resolves.toBeUndefined()
  })

  it('非 JSON 响应体包装成 NetworkError', async () => {
    stubFetch(async () => ({ status: 502, text: async () => '<html>gateway</html>' } as Response))
    await expect(http.get('/x')).rejects.toBeInstanceOf(NetworkError)
  })

  it('Fetch 自身失败包装成 NetworkError', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
    await expect(http.get('/x')).rejects.toBeInstanceOf(NetworkError)
  })

  it('用户主动取消不被包装成网络错误', async () => {
    const controller = new AbortController()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init: RequestInit) => {
        if (init.signal?.aborted === true) throw new DOMException('aborted', 'AbortError')
        return ok({})
      }),
    )
    await expect(http.get('/x', undefined, { signal: controller.signal })).resolves.toEqual({})
  })
})

describe('401 → 刷新 → 重试', () => {
  it('刷新后用新令牌重试，原始请求成功', async () => {
    const fetchStub = stubFetch(async (call, nth) => {
      if (call.url.includes('/auth/refresh')) return ok(makeTokenPair('access-2', 'refresh-2'))
      if (nth === 1) return unauthorized()
      return ok({ id: '1' })
    })

    await expect(http.get<{ id: string }>('/admin/users')).resolves.toEqual({ id: '1' })

    // 1 次原始请求 + 1 次刷新 + 1 次重试。
    expect(fetchStub.calls).toHaveLength(3)
    expect(refreshMock).toHaveBeenCalledTimes(1)
    expect(onSessionLostMock).not.toHaveBeenCalled()
    // 重试必须带上刷新后的令牌，否则等于白刷一次。
    // 这里的值来自假后端 `/auth/refresh` 的响应（access-2），桥接层写回 store
    // 后由下一次 `requestOnce` 读出来 —— 断言必须与假后端一致，不能凭印象写。
    expect(headerOf(fetchStub.calls[2]!, 'Authorization')).toBe('Bearer access-2')
  })

  it('并发 401 只刷新一次（单实例刷新）', async () => {
    const fetchStub = stubFetch(async (call) => {
      if (call.url.includes('/auth/refresh')) return ok(makeTokenPair('access-2', 'refresh-2'))
      return unauthorized()
    })

    const results = await Promise.allSettled([http.get('/a'), http.get('/b'), http.get('/c')])

    expect(refreshMock).toHaveBeenCalledTimes(1)
    expect(fetchStub.calls.filter((call) => call.url.includes('/auth/refresh'))).toHaveLength(1)
    // 3 次原始 + 3 次重试，全部失败。
    expect(fetchStub.calls.filter((call) => !call.url.includes('/auth/refresh'))).toHaveLength(6)
    expect(results.every((item) => item.status === 'rejected')).toBe(true)
    // "会话已失效"是一条事实，不是每个请求各报一次事件：
    // 三个重试都 401 其实是同一次结论被观察到三次，通知一次就够。
    expect(onSessionLostMock).toHaveBeenCalledTimes(1)
  })

  it('并发刷新成功后，每个请求的重试都带新令牌', async () => {
    const fetchStub = stubFetch(async (call, nth) => {
      if (call.url.includes('/auth/refresh')) return ok(makeTokenPair('access-2', 'refresh-2'))
      if (nth <= 2) return unauthorized()
      return ok({ ok: true })
    })

    await Promise.all([http.get('/a'), http.get('/b')])

    expect(refreshMock).toHaveBeenCalledTimes(1)
    const business = fetchStub.calls.filter((call) => !call.url.includes('/auth/refresh'))
    expect(business).toHaveLength(4)
    expect(headerOf(business[2]!, 'Authorization')).toBe('Bearer access-2')
    expect(headerOf(business[3]!, 'Authorization')).toBe('Bearer access-2')
  })

  it('刷新后仍 401 时调用次数有上界（不产生刷新风暴）', async () => {
    const fetchStub = stubFetch(async (call) => {
      if (call.url.includes('/auth/refresh')) return ok(makeTokenPair('access-2', 'refresh-2'))
      return unauthorized()
    })

    await expect(http.get('/x')).rejects.toBeInstanceOf(UnauthorizedError)

    // 1 次原始 + 1 次刷新 + 1 次重试，到此为止 —— 不再进入下一轮刷新。
    expect(fetchStub.calls).toHaveLength(3)
    expect(refreshMock).toHaveBeenCalledTimes(1)
    expect(onSessionLostMock).toHaveBeenCalledWith('refresh_failed')
  })

  it('刷新接口返回 401 也触发登出', async () => {
    stubFetch(async () => unauthorized('refresh token revoked'))
    refreshMock.mockRejectedValue(new UnauthorizedError(401001, 'refresh token revoked', 401))

    await expect(http.get('/x')).rejects.toBeInstanceOf(UnauthorizedError)
    expect(onSessionLostMock).toHaveBeenCalledWith('refresh_failed')
  })

  it('刷新时的网络错误同样触发登出，并归一成 UnauthorizedError', async () => {
    stubFetch(async () => unauthorized())
    refreshMock.mockRejectedValue(new NetworkError('network down', ''))

    await expect(http.get('/x')).rejects.toBeInstanceOf(UnauthorizedError)
    expect(onSessionLostMock).toHaveBeenCalledWith('refresh_failed')
  })

  it('重试仍失败时的网络错误不会误触发登出（会话本身是好的）', async () => {
    // 关键：刷新本身**必须成功**，否则重试根本不会发生（失败发生在刷新阶段时
    // 已经走了"刷新失败即登出"，那是另一条用例）。网络错误只发生在重试上。
    let firstAttempt = true
    stubFetch(async (call) => {
      if (call.url.includes('/auth/refresh')) return ok(makeTokenPair('access-2', 'refresh-2'))
      if (firstAttempt) {
        firstAttempt = false
        return unauthorized()
      }
      throw new Error('network down')
    })

    await expect(http.get('/x')).rejects.toBeInstanceOf(NetworkError)
    expect(onSessionLostMock).not.toHaveBeenCalled()
  })

  it('没有 Refresh Token 时不发刷新请求，直接登出', async () => {
    tokens.refresh = null
    const fetchStub = stubFetch(async () => unauthorized())
    await expect(http.get('/x')).rejects.toBeInstanceOf(UnauthorizedError)
    expect(refreshMock).not.toHaveBeenCalled()
    expect(fetchStub.calls).toHaveLength(1)
    expect(onSessionLostMock).toHaveBeenCalledWith('refresh_failed')
  })
})

describe('403 → 权限拒绝（不是登录失效）', () => {
  it('403 不当成登录失效：不刷新、不重试、不登出', async () => {
    const fetchStub = stubFetch(async () => forbidden())
    await expect(http.get('/admin/users')).rejects.toBeInstanceOf(ForbiddenError)
    expect(fetchStub.calls).toHaveLength(1)
    expect(refreshMock).not.toHaveBeenCalled()
    expect(onSessionLostMock).not.toHaveBeenCalled()
  })

  it('HTTP 403 即使业务码是别的数值也判为权限拒绝', async () => {
    stubFetch(async () => fail(403001, 'no', 403))
    await expect(http.get('/x')).rejects.toBeInstanceOf(ForbiddenError)
  })
})

describe('刷新槽位', () => {
  it('刷新结束后槽位释放，下一次 401 还能再刷', async () => {
    let refreshCount = 0
    const gate = rejectFirstPerUrl()
    stubFetch(async (call) => {
      if (call.url.includes('/auth/refresh')) {
        refreshCount += 1
        return ok(makeTokenPair(`access-r${refreshCount}`, `refresh-r${refreshCount}`))
      }
      return gate.handler(call)
    })

    await http.get('/first')
    expect(hasRefreshInFlight()).toBe(false)
    expect(refreshCount).toBe(1)

    // 第二个 URL 第一次尝试同样被拒 —— 槽位若没释放，这里就再刷不了第二次。
    await expect(http.get('/second')).resolves.toEqual({ ok: true })
    expect(refreshCount).toBe(2)
  })

  it('刷新进行中槽位非空', async () => {
    const gate = rejectFirstPerUrl()
    // 用容器装而不是 `let`：直接对闭包里的 `let` 做可选调用时，
    // 类型检查会把它的收窄结果算成 `never`，改成"看起来绕"的写法反而更省事。
    const gate2: { release: (() => void) | null } = { release: null }
    const gate2Promise = new Promise<void>((resolve) => {
      gate2.release = resolve
    })
    stubFetch(async (call) => {
      if (call.url.includes('/auth/refresh')) {
        await gate2Promise
        return ok(makeTokenPair('access-r1', 'refresh-r1'))
      }
      return gate.handler(call)
    })

    const pending = http.get('/x')
    await until(() => hasRefreshInFlight())
    expect(hasRefreshInFlight()).toBe(true)

    gate2.release?.()
    // 刷新放行后重试用新令牌，拿到成功响应。
    await expect(pending).resolves.toEqual({ ok: true })
    expect(hasRefreshInFlight()).toBe(false)
  })
})

describe('nextRequestId', () => {
  it('输出的标识非空且互不相同', () => {
    const ids = new Set(Array.from({ length: 50 }, () => nextRequestId()))
    expect(ids.size).toBe(50)
    for (const id of ids) expect(id.length).toBeGreaterThan(0)
  })
})
