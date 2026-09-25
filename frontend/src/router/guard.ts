/**
 * 路由守卫（FE-02 §4 / FE-04）。
 *
 * 守卫处理七件事：未登录、Token 过期、权限未加载、无页面权限、403、Logout、
 * 被踢下线。FE-12 §3 的集成测试要覆盖其中六条，因此判定逻辑写成纯函数
 * `decideNavigation`，守卫只负责拿到上下文后调用它。
 *
 * `decideNavigation` 是**纯函数**：它的每个分支都有一条单测（见
 * `tests/router/guard.spec.ts`）。守卫里出现的分支才算"行为"，
 * 判定里的分支算"契约" —— 两者不能混写，否则改一个判定会连带改掉守卫。
 */

export const LOGIN_PATH = '/login'
export const FORBIDDEN_PATH = '/403'
export const HOME_PATH = '/dashboard'

export interface GuardContext {
  /** 目标路径（不含 query）。 */
  to: string
  isAuthenticated: boolean
  /** 权限契约是否已加载。未加载时守卫**等待加载完成**再判定。 */
  permissionsLoaded: boolean
  /** 目标路由声明的页面权限编码。 */
  requiredPermission?: string | undefined
  hasPermission: (code: string) => boolean
}

export type GuardDecision =
  /** 放行。 */
  | { kind: 'next' }
  /** 等待异步加载完成后重新进入（守卫会 await 后重试）。 */
  | { kind: 'wait' }
  | { kind: 'redirect'; to: string }

export function decideNavigation(context: GuardContext): GuardDecision {
  const { to, isAuthenticated, permissionsLoaded, requiredPermission, hasPermission } = context

  // 1. 已登录用户不该停在登录页。
  if (to === LOGIN_PATH && isAuthenticated) {
    return { kind: 'redirect', to: HOME_PATH }
  }

  // 2. 未登录：带上来源路径，登录后能回到原处。
  //    回跳目标会被限制在站内（FE-11 §7 Open Redirect）。
  //
  //    但登录页自身**必须放行**。这里曾经不区分"目标是不是登录页"，于是
  //    未登录访问 `/login` 会走进这条分支，被自己踢回 `/login?redirect=/login` ——
  //    vue-router 直接判 infinite redirect，登录页永远打不开（实测）。
  if (!isAuthenticated) {
    if (to === LOGIN_PATH) return { kind: 'next' }
    return { kind: 'redirect', to: `${LOGIN_PATH}?redirect=${encodeURIComponent(to)}` }
  }

  // 3. 权限还没加载：不能判定"无权限"，否则会误伤成 403。
  if (!permissionsLoaded) {
    return { kind: 'wait' }
  }

  // 4. 有页面权限要求但拿不到 → 403 页（不是登录页）。
  if (requiredPermission !== undefined && requiredPermission !== '' && !hasPermission(requiredPermission)) {
    return { kind: 'redirect', to: FORBIDDEN_PATH }
  }

  return { kind: 'next' }
}

/** Open Redirect 防护（FE-11 §7）：只接受站内绝对路径，且必须以 `/` 开头。 */
export function sanitizeRedirect(raw: string | null, fallback: string = HOME_PATH): string {
  if (raw === null || raw === '') return fallback
  // 拒绝协议相对 URL（//evil.com）与其它协议（javascript: 等）。
  if (raw.startsWith('//') || /^[a-z][a-z0-9+.-]*:/i.test(raw)) return fallback
  if (!raw.startsWith('/')) return fallback
  const [pathPart = ''] = raw.split('?')
  if (pathPart === '' || pathPart === '/') return fallback
  const segments = pathPart.split('/')
  // 拒绝反斜杠伪装（浏览器把 `\` 当 `/`）与 `.` / `..` 段（会跳到别的路由上）。
  if (segments.some((segment) => segment.includes('\\') || segment === '.' || segment === '..')) {
    return fallback
  }
  return raw
}
