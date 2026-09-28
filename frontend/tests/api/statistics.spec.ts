import { beforeEach, describe, expect, it } from 'vitest'
import { configureClient } from '@/api/client'
import { getStatisticsOverview } from '@/api/endpoints/statistics'
import type { AuthBridge } from '@/api/client'
import { fail, ok, stubFetch } from '../helpers/fetchMock'
import { makeTokenPair } from '../helpers/fixtures'
import type { StatisticsOverview } from '@/types'

/**
 * 报表统计端点的**路径与信封**（`08 §2`）。
 *
 * 为什么值得单独一条：前端按"应该有"去拼路径，在后端不存在时**不会**在
 * 类型检查或构建期暴露，只有真跑起来才看到 404。项目里已经踩过一次
 * （`organization.ts` 模块注释记录的 `GET /admin/users/{id}/roles` 并不存在）。
 *
 * 第二条用例断言**403 会抛出**：报表本身不做整体 403（无权限的域用
 * `accessible:false` 表达），因此真收到 403 说明是别的问题，
 * 必须如实冒泡而不是被静默吞成"看起来一切正常"。
 */

beforeEach(() => {
  const bridge: AuthBridge = {
    getAccessToken: () => 'access-1',
    getRefreshToken: () => 'refresh-1',
    refresh: async () => makeTokenPair(),
    onSessionLost: () => undefined,
  }
  configureClient({ baseUrl: '/api/v1/', bridge })
})

function overview(): StatisticsOverview {
  return {
    generated_at: '2026-09-28T06:00:00Z',
    scope_policy: 'ALL',
    users: { accessible: true, total: 39, active: 38, disabled: 1 },
    sessions: { accessible: true, online_users: 2, online_sessions: 5, total: 41 },
    departments: { accessible: true, total: 6 },
    roles: { accessible: true, total: 6 },
    audit: { accessible: true, today: 13, total: 3401 },
  }
}

describe('getStatisticsOverview', () => {
  it('打到 /admin/statistics/overview，且解包信封里的 data', async () => {
    const fetchStub = stubFetch(async () => ok(overview()))

    const result = await getStatisticsOverview()

    expect(fetchStub.calls).toHaveLength(1)
    const call = fetchStub.calls[0]
    expect(call?.url).toBe('/api/v1/admin/statistics/overview')
    expect(call?.init.method).toBe('GET')
    // `online_users` 与 `online_sessions` 是两个不同的字段，不能被解包时合并掉。
    expect(result.sessions.online_users).toBe(2)
    expect(result.sessions.online_sessions).toBe(5)
  })

  it('分组不可见时保留 null，不被兜底成 0', async () => {
    const payload = overview()
    payload.roles = { accessible: false, total: null }
    payload.audit = { accessible: false, today: null, total: null }
    stubFetch(async () => ok(payload))

    const result = await getStatisticsOverview()

    expect(result.roles).toEqual({ accessible: false, total: null })
    // 关键：null 必须原样透出。"无权限"与"一个都没有"是两件事，
    // 客户端把 null 兜成 0 就等于替后端编了一个假数字。
    expect(result.audit.total).toBeNull()
    expect(result.audit.today).not.toBe(0)
  })

  it('真的收到 403 时如实抛出（报表不用 accessible 之外的机制表达无权限）', async () => {
    stubFetch(async () => fail(403001, 'permission denied', 403))

    await expect(getStatisticsOverview()).rejects.toThrow()
  })
})
