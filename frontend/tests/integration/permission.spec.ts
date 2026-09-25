import { beforeEach, describe, expect, it } from 'vitest'
import { router, installDynamicRoutes, installHttpClient } from '@/router'
import { usePermissionStore } from '@/stores/permission'
import { ok, stubFetch } from '../helpers/fetchMock'
import { buildContract, FULL_PAGE_SPECS, pageSpec } from '../helpers/fixtures'

/**
 * 权限更新 → 刷新（FE-12 §3 第六项：permission update → refresh）。
 *
 * FE-03 §5 的原话是"不得假定权限永久缓存"。这条要求如果只写成一个
 * `refresh()` 方法而没有任何调用方，就等于没实现 —— 所以这里测的是
 * **真实的触发条件**：改了某个角色的配置，只有当前用户持有该角色时才重拉。
 */

const PERMISSIONS_PATH = '/api/v1/auth/permissions'
const PAGES_PERMISSION_PATH = /\/admin\/roles\/\d+\/permissions\/pages$/

const ROLE_ID = '9001'
const OTHER_ROLE_ID = '9009'

let contractCallCount = 0

/** 第二次起返回"新版"契约：多一个页面、版本 +1。 */
function v1Contract() {
  return buildContract({ permissionVersion: 1, directRoleIds: [ROLE_ID], inheritedRoleIds: [] })
}

function v2Contract() {
  return buildContract({
    permissionVersion: 2,
    directRoleIds: [ROLE_ID],
    inheritedRoleIds: [],
    pages: [...FULL_PAGE_SPECS, pageSpec('system:extra:page', '/system/extra', '/system/param')],
  })
}

beforeEach(() => {
  contractCallCount = 0
  stubFetch(async (call) => {
    const url = call.url
    if (url === PERMISSIONS_PATH) {
      contractCallCount += 1
      return ok(contractCallCount <= 1 ? v1Contract() : v2Contract())
    }
    if (PAGES_PERMISSION_PATH.test(url)) return ok(null)
    if (url === '/api/v1/auth/me') {
      return ok({
        id: '7001',
        username: 'admin',
        display_name: '管理员',
        department_id: null,
        status: 'ACTIVE',
        must_change_password: false,
        password_expired: false,
      })
    }
    return ok(null)
  })
  installHttpClient()
})

function pathExists(path: string): boolean {
  return router.getRoutes().some((route) => route.path === path)
}

describe('权限更新后的契约刷新', () => {
  it('当前用户持有被改角色时，保存后重拉契约并入账新路由', async () => {
    const permissionStore = usePermissionStore()
    await permissionStore.load()
    expect(permissionStore.version).toBe(1)

    installDynamicRoutes(permissionStore.toContract())
    expect(pathExists('/system/extra')).toBe(false)

    // 模拟"给当前管理员持有的角色勾了新权限"：保存成功后重拉。
    const refreshed = await permissionStore.refreshIfHoldsRole([ROLE_ID])

    expect(refreshed).toBe(true)
    expect(permissionStore.version).toBe(2)
    expect(permissionStore.hasPagePermission('system:extra:page')).toBe(true)

    // 重装路由时旧的会被清掉，不会出现"已经没权限了路由还在"。
    installDynamicRoutes(permissionStore.toContract())
    expect(pathExists('/system/extra')).toBe(true)
  })

  it('当前用户不持有该角色时不浪费一次请求', async () => {
    const permissionStore = usePermissionStore()
    await permissionStore.load()
    const before = contractCallCount

    const refreshed = await permissionStore.refreshIfHoldsRole([OTHER_ROLE_ID])

    expect(refreshed).toBe(false)
    expect(contractCallCount).toBe(before)
  })

  it('持有角色时一定会重拉（哪怕契约没变，也要按版本对账）', async () => {
    const permissionStore = usePermissionStore()
    await permissionStore.load()
    const before = contractCallCount

    await expect(permissionStore.refreshIfHoldsRole([ROLE_ID])).resolves.toBe(true)

    expect(contractCallCount).toBeGreaterThan(before)
  })

  it('刷新失败不影响已保存的配置，也不让守卫继续等待', async () => {
    let permissionsCalls = 0
    stubFetch(async (call) => {
      if (call.url === PERMISSIONS_PATH) {
        permissionsCalls += 1
        // 首次拉取成功，只让"保存后的同步"这一步失败。
        if (permissionsCalls > 1) throw new Error('network')
        return ok(v1Contract())
      }
      return ok(null)
    })

    const permissionStore = usePermissionStore()
    await permissionStore.load()

    await expect(permissionStore.refreshIfHoldsRole([ROLE_ID])).rejects.toThrow()
    // 保存已经成功，配置不能因为刷新这一步失败而被回滚；
    // loaded 保持为真，页面落到 403 而不是一直转圈。
    expect(permissionStore.isLoaded).toBe(true)
  })

  it('已加载状态下重复 load 不会重复请求（避免刷新风暴）', async () => {
    const permissionStore = usePermissionStore()
    await permissionStore.load()
    const before = contractCallCount

    await permissionStore.load()

    expect(contractCallCount).toBe(before)
  })
})
