import { beforeEach, describe, expect, it, vi } from 'vitest'
import { bootstrapSession } from '@/stores/bootstrapSession'
import { useAuthStore } from '@/stores/auth'
import { usePermissionStore } from '@/stores/permission'
import * as authApi from '@/api/endpoints/auth'
import * as permissionApi from '@/api/endpoints/permissions'
import { NetworkError } from '@/api/errors'
import { buildContract } from '../helpers/fixtures'

/**
 * 启动装配（badge）。
 *
 * 这里覆盖的不是"界面长什么样"，而是**入口文件的顺序逻辑**是否还在：
 * 身份回填与权限预加载都写在 `main.ts` 里时，删掉任意一行都不会有任何测试
 * 变红，缺陷只在浏览器里现身（顶栏停在「未登录」）。抽出来就是为了能测。
 */

vi.mock('@/api/endpoints/auth', () => ({
  login: vi.fn(),
  verifyMfa: vi.fn(),
  refresh: vi.fn(),
  logout: vi.fn(),
  getMe: vi.fn(),
  changePassword: vi.fn(),
  getMfaStatus: vi.fn(),
  setupMfa: vi.fn(),
  enableMfa: vi.fn(),
  disableMfa: vi.fn(),
}))

vi.mock('@/api/endpoints/permissions', () => ({
  getPermissionContract: vi.fn(),
  listPermissionResources: vi.fn(),
  createPermissionResource: vi.fn(),
  updatePermissionResource: vi.fn(),
  deletePermissionResource: vi.fn(),
}))

const api = vi.mocked(authApi)
const permApi = vi.mocked(permissionApi)

/** 令牌是 authStore 的模块级内存变量，不随 pinia 重置 —— 每条用例前手动清。 */
beforeEach(() => {
  useAuthStore().clearSession()
  window.localStorage.clear()
  api.getMe.mockReset()
  permApi.getPermissionContract.mockReset()
})

describe('bootstrapSession', () => {
  it('令牌还在时，补身份 + 预加载权限', async () => {
    window.localStorage.setItem('vctn.access_token', 'access-old')
    window.localStorage.setItem('vctn.refresh_token', 'refresh-old')
    api.getMe.mockResolvedValue({
      id: '7001',
      username: 'admin',
      display_name: '管理员',
      department_id: null,
      status: 'ACTIVE',
      must_change_password: false,
      password_expired: false,
    })
    permApi.getPermissionContract.mockResolvedValue(buildContract())

    await bootstrapSession()

    const authStore = useAuthStore()
    expect(authStore.user?.display_name).toBe('管理员')
    expect(usePermissionStore().isLoaded).toBe(true)
  })

  it('没有令牌时一个请求都不发（未登录不该去碰受保护接口）', async () => {
    await bootstrapSession()

    expect(api.getMe).not.toHaveBeenCalled()
    expect(permApi.getPermissionContract).not.toHaveBeenCalled()
  })

  it('任一路失败都不把应用炸掉 —— 启动阶段的失败留给用户导航时再判', async () => {
    window.localStorage.setItem('vctn.access_token', 'access-old')
    api.getMe.mockRejectedValue(new NetworkError('网络请求失败', ''))
    permApi.getPermissionContract.mockRejectedValue(new NetworkError('网络请求失败', ''))

    await expect(bootstrapSession()).resolves.toBeUndefined()

    expect(useAuthStore().isAuthenticated).toBe(true)
  })

  it('令牌被写回内存后才算"可以用"，restorePersistedTokens 不是装饰', async () => {
    window.localStorage.setItem('vctn.access_token', 'access-old')
    api.getMe.mockResolvedValue({
      id: '7001',
      username: 'admin',
      display_name: '管理员',
      department_id: null,
      status: 'ACTIVE',
      must_change_password: false,
      password_expired: false,
    })
    permApi.getPermissionContract.mockResolvedValue(buildContract())

    await bootstrapSession()

    expect(useAuthStore().accessTokenValue).toBe('access-old')
  })
})
