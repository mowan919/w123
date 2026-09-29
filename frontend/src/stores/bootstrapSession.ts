import { useAuthStore } from '@/stores/auth'
import { usePermissionStore } from '@/stores/permission'

/**
 * 启动时的会话装配。
 *
 * 为什么要从 `main.ts` 里抽出来
 * ----------------------------
 * `main.ts` 里的代码**没有任何测试能碰到它**（一跑就会 `createApp().mount()`，
 * 与真实 DOM、真实路由纠缠在一起）。而这里做的事恰恰是最容易被人"顺手删掉
 * 一行"的那类：删掉身份回填，页面照常工作，只是顶栏永远显示「未登录」——
 * 单测全绿，缺陷只在浏览器里现身。
 *
 * 抽成纯函数后，这条链路可以被单元测覆盖到：
 * 变异验证里把 `hydrate()` 那一行去掉，测试立刻变红（历史上这正是
 * M6 那个"抓不到"的变异）。
 *
 * 代价：`main.ts` 只剩三行。这恰恰是想要的结果 ——
 * 入口文件不应该承载"先做再做"的顺序逻辑。
 */
export async function bootstrapSession(): Promise<void> {
  const authStore = useAuthStore()
  const permissionStore = usePermissionStore()

  // 恢复持久化令牌：只恢复令牌，**不**把 user 填回来 —— 用户身份必须由
  // `GET /auth/me` 与 `GET /auth/permissions` 在服务端确认后才有意义。
  const { access, refresh } = authStore.restorePersistedTokens()
  if (access === null && refresh === null) return

  // 两个请求各自吞掉失败：
  // - `hydrate()` 的失败信息有用与否由它自己判断（401 已内部转成清会话）；
  // - 权限加载失败时 `permissionStore.load()` 会把 `loaded` 置 true 并抛出，
  //   这里吞掉是为了让守卫在用户真正导航时再走一遍判定 —— 那时会拿到
  //   真实结果，而不是在启动阶段就把用户甩到登录页。
  await Promise.all([
    authStore.hydrate().catch(() => undefined),
    permissionStore.load().catch(() => undefined),
  ])
}
