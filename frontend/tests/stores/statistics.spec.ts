import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/endpoints/statistics', () => ({
  getStatisticsOverview: vi.fn(),
}))

import * as statisticsApi from '@/api/endpoints/statistics'
import { useStatisticsStore } from '@/stores/statistics'
import type { StatisticsOverview } from '@/types'

const api = vi.mocked(statisticsApi)

function overview(overrides: Partial<StatisticsOverview> = {}): StatisticsOverview {
  return {
    generated_at: '2026-09-28T06:00:00Z',
    scope_policy: 'ALL',
    users: { accessible: true, total: 39, active: 38, disabled: 1 },
    sessions: { accessible: true, online_users: 2, online_sessions: 5, total: 41 },
    departments: { accessible: true, total: 6 },
    roles: { accessible: true, total: 6 },
    audit: { accessible: true, today: 13, total: 3401 },
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('statisticsStore.load', () => {
  it('首次加载写入 overview 并置 loaded', async () => {
    api.getStatisticsOverview.mockResolvedValue(overview())
    const store = useStatisticsStore()

    await store.load()

    expect(store.overview?.users.total).toBe(39)
    expect(store.loaded).toBe(true)
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('重复 load 不再打请求（页面来回切换不该每次都跑一次聚合查询）', async () => {
    api.getStatisticsOverview.mockResolvedValue(overview())
    const store = useStatisticsStore()

    await store.load()
    await store.load()

    expect(api.getStatisticsOverview).toHaveBeenCalledTimes(1)
  })

  it('refresh() 明确要求重新拉取', async () => {
    api.getStatisticsOverview.mockResolvedValue(overview())
    const store = useStatisticsStore()

    await store.load()
    await store.refresh()

    expect(api.getStatisticsOverview).toHaveBeenCalledTimes(2)
  })

  it('刷新失败时保留上一次的数字（并给出错误），而不是清成空屏', async () => {
    // 空屏无法区分"没有权限"与"请求挂了"，后者应当保留可用信息 + 明确报错。
    const store = useStatisticsStore()
    api.getStatisticsOverview.mockResolvedValue(overview())
    await store.load()

    api.getStatisticsOverview.mockRejectedValue(new Error('network down'))
    await store.refresh()

    expect(store.overview?.users.total).toBe(39)
    expect(store.error).toBe('network down')
    expect(store.loading).toBe(false)
  })

  it('首次加载就失败时不残留 loaded（下次进入还会重试）', async () => {
    api.getStatisticsOverview.mockRejectedValue(new Error('boom'))
    const store = useStatisticsStore()

    await store.load()

    expect(store.loaded).toBe(false)
    expect(store.overview).toBeNull()
    expect(store.error).toBe('boom')
  })
})

describe('statisticsStore.reset', () => {
  it('清掉快照与全部标志位（换账号不能看到上一个人的数字）', async () => {
    api.getStatisticsOverview.mockResolvedValue(overview())
    const store = useStatisticsStore()
    await store.load()

    store.reset()

    expect(store.overview).toBeNull()
    expect(store.loaded).toBe(false)
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })
})

describe('generatedAtText', () => {
  it('未加载时为 null；加载后给出本地化文本', async () => {
    api.getStatisticsOverview.mockResolvedValue(overview())
    const store = useStatisticsStore()
    expect(store.generatedAtText).toBeNull()

    await store.load()

    expect(store.generatedAtText).not.toBeNull()
    expect(typeof store.generatedAtText).toBe('string')
  })

  it('时间戳非法时不编造文本', async () => {
    api.getStatisticsOverview.mockResolvedValue(overview({ generated_at: 'not-a-date' }))
    const store = useStatisticsStore()

    await store.load()

    expect(store.generatedAtText).toBeNull()
  })
})
