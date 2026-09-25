import { describe, expect, it, vi } from 'vitest'
import {
  decideNavigation,
  FORBIDDEN_PATH,
  HOME_PATH,
  LOGIN_PATH,
  sanitizeRedirect,
} from '@/router/guard'

/**
 * 路由守卫（FE-02 §4 / FE-11 §7 / FE-12 §2）。
 *
 * 两条最容易写反、且写反后不容易察觉的判定：
 *
 * 1. **权限未加载 ≠ 无权限**。若把 `!permissionsLoaded` 直接判成 403，
 *    刷新页面（首次进入守卫时契约必然还没回来）会 Every time 落到 403。
 * 2. **Open Redirect 防护**。回跳目标来自 URL query，是唯一一处"用户可控
 *    却会被浏览器当成本站地址"的输入。
 */

function context(overrides: Partial<Parameters<typeof decideNavigation>[0]> = {}) {
  return {
    to: '/system/users',
    isAuthenticated: true,
    permissionsLoaded: true,
    requiredPermission: undefined as string | undefined,
    hasPermission: (_code: string) => true,
    ...overrides,
  }
}

describe('decideNavigation', () => {
  it('未登录时带上来源路径跳登录页', () => {
    const decision = decideNavigation(context({ isAuthenticated: false }))
    expect(decision).toEqual({ kind: 'redirect', to: `${LOGIN_PATH}?redirect=%2Fsystem%2Fusers` })
  })

  it('来源路径做了 URL 编码（含 & 的路径不能截断开）', () => {
    const decision = decideNavigation(context({ isAuthenticated: false, to: '/a?x=1&y=2' }))
    if (decision.kind !== 'redirect') throw new Error('expected redirect')
    expect(decision.to).toContain('redirect=%2Fa%3Fx%3D1%26y%3D2')
  })

  it('已登录用户在登录页会被送到首页', () => {
    expect(decideNavigation(context({ to: LOGIN_PATH }))).toEqual({
      kind: 'redirect',
      to: HOME_PATH,
    })
  })

  it('权限未加载时返回 wait，而不是 403', () => {
    const decision = decideNavigation(context({ permissionsLoaded: false }))
    expect(decision).toEqual({ kind: 'wait' })
  })

  it('无权限要求时直接放行', () => {
    expect(decideNavigation(context())).toEqual({ kind: 'next' })
  })

  it('有页面权限要求但拿不到 → 403 页', () => {
    const decision = decideNavigation(
      context({ requiredPermission: 'system:user:page', hasPermission: () => false }),
    )
    expect(decision).toEqual({ kind: 'redirect', to: FORBIDDEN_PATH })
  })

  it('403 不会被当成登录失效（不会绕回登录页）', () => {
    const decision = decideNavigation(
      context({ requiredPermission: 'system:user:page', hasPermission: () => false }),
    )
    expect(decision).toEqual({ kind: 'redirect', to: FORBIDDEN_PATH })
    // 显式排除"跳回登录页"这个反模式：无权限不等于没登录，
    // 把两者混用会让用户反复被踢回登录页却没有提示。
    expect(decision).not.toEqual({ kind: 'redirect', to: LOGIN_PATH })
  })

  it('权限要求为空串时按"无要求"处理', () => {
    // 防御式：路由 meta 写空串不该把所有人都拦到 403。
    expect(decideNavigation(context({ requiredPermission: '' }))).toEqual({ kind: 'next' })
  })

  it('hasPermission 只在需要判定时被调用', () => {
    const hasPermission = vi.fn(() => false)
    decideNavigation(context({ hasPermission }))
    // 无权限要求的路由不该去问 store —— 每次导航都问一遍会让"谁触发了取权限"无法追溯。
    expect(hasPermission).not.toHaveBeenCalled()
  })
})

describe('sanitizeRedirect', () => {
  it('空值回落到默认首页', () => {
    expect(sanitizeRedirect(null)).toBe(HOME_PATH)
    expect(sanitizeRedirect('')).toBe(HOME_PATH)
  })

  it('接受站内绝对路径', () => {
    expect(sanitizeRedirect('/system/users')).toBe('/system/users')
    expect(sanitizeRedirect('/system/users?a=1&b=2')).toBe('/system/users?a=1&b=2')
  })

  it('拒绝协议相对 URL（//evil.com 在浏览器里会跳出站点）', () => {
    expect(sanitizeRedirect('//evil.com')).toBe(HOME_PATH)
    expect(sanitizeRedirect('///evil.com')).toBe(HOME_PATH)
  })

  it('拒绝其它协议', () => {
    expect(sanitizeRedirect('https://evil.com')).toBe(HOME_PATH)
    expect(sanitizeRedirect('http://evil.com')).toBe(HOME_PATH)
    expect(sanitizeRedirect('javascript:alert(1)')).toBe(HOME_PATH)
    expect(sanitizeRedirect('data:text/html,<script>')).toBe(HOME_PATH)
  })

  it('拒绝反斜杠伪装（浏览器会把 \\ 当 / 解析）', () => {
    expect(sanitizeRedirect('/\\evil.com')).toBe(HOME_PATH)
    expect(sanitizeRedirect('/system\\users')).toBe(HOME_PATH)
  })

  it('拒绝根路径、相对路径与路径穿越段', () => {
    expect(sanitizeRedirect('/')).toBe(HOME_PATH)
    expect(sanitizeRedirect('system/users')).toBe(HOME_PATH)
    // `..` 会跳到一个并非用户点选的路由上；宁可回落首页。
    expect(sanitizeRedirect('/system/users/../secret')).toBe(HOME_PATH)
    expect(sanitizeRedirect('/./system/users')).toBe(HOME_PATH)
  })

  it('自定义回落值生效', () => {
    expect(sanitizeRedirect('//evil.com', '/login')).toBe('/login')
  })
})
