import { beforeEach, describe, expect, it } from 'vitest'
import { configureClient } from '@/api/client'
import { putRoleGrant } from '@/api/endpoints/roles'
import type { AuthBridge } from '@/api/client'
import { ok, stubFetch } from '../helpers/fetchMock'
import { makeTokenPair } from '../helpers/fixtures'

/**
 * 按类别分派授权提交（`08 §7`）。
 *
 * 四个端点的语义完全一致，差异**只在路径**：漏写 / 写错一个分支不会报错，
 * 只会表现为"某一类权限怎么都存不上"，而且看日志也只能看到"保存成功"。
 *
 * ⚠️ 这里刻意用**真实实现 + 假 fetch**，而不是 `vi.mock` 掉底层四个函数再
 * 断言它们被调用 —— 踩过的坑：`putRoleGrant` 保持真实实现时，它调用的是
 * **同模块内的原始函数**，测试里 `vi.mock` 出来的替身根本收不到调用，
 * 于是"断言全绿"而实际什么都没验证到。断言请求本身才是真的。
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

describe('putRoleGrant 按类别分派到四个端点', () => {
  it.each([
    ['PAGE', 'pages'],
    ['MENU', 'menus'],
    ['BUTTON', 'buttons'],
    ['API', 'apis'],
  ] as const)('%s → /admin/roles/{id}/permissions/%s', async (kind, segment) => {
    const fetchStub = stubFetch(async () => ok(null))

    await putRoleGrant(kind, '9001', ['r1', 'r2'])

    expect(fetchStub.calls).toHaveLength(1)
    const call = fetchStub.calls[0]
    expect(call?.url).toBe(`/api/v1/admin/roles/9001/permissions/${segment}`)
    expect(call?.init.method).toBe('PUT')
    // 请求体是 `resourceIds`（不是 `ids` / `resource_ids`）—— 后端契约如此。
    expect(JSON.parse(String(call?.init.body))).toEqual({ resourceIds: ['r1', 'r2'] })
  })

  it('空集合也照常提交（"清空该类授权"是合法操作，不能被当成空操作跳过）', async () => {
    const fetchStub = stubFetch(async () => ok(null))

    await putRoleGrant('BUTTON', '9001', [])

    expect(fetchStub.calls).toHaveLength(1)
    expect(JSON.parse(String(fetchStub.calls[0]?.init.body))).toEqual({ resourceIds: [] })
  })
})
