import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { generateRoutes, normalizeComponentPath, resolveView, toRouteRecords, VIEW_REGISTRY } from '@/router/generate'
import type { PermissionContract } from '@/types'
import { buildContract, FULL_PAGE_SPECS, pageSpec } from '../helpers/fixtures'

/**
 * 动态路由生成器（FE-02 §2 / FE-12 §2）。
 *
 * 这里最容易出的一类错是"注册表里写了键、对应视图文件却不存在（或已改名）"。
 * 它不会让构建失败（`defineAsyncComponent` 只在被导航时才真正加载），
 * 只会表现为"点开菜单白屏"，所以必须由测试钉住。
 */

/**
 * 源码目录。
 *
 * 这里**不能**用 `fileURLToPath(new URL('../../src', import.meta.url))`：
 * 在 jsdom 环境下 Vitest 会把模块作用域里 `new URL(x, import.meta.url)` 解析成
 * `http://localhost:3000/@fs/D:/...`（http 而不是 file），传给 `fileURLToPath`
 * 就直接抛 "The URL must be of scheme file"。同一个表达式写在用例函数体里反而
 * 拿到正确的 file URL —— 这类"模块作用域与函数作用域取值不同"的行为不适合拿来
 * 支撑断言，改用进程 cwd（Vitest 固定以工程根为 cwd）既稳又直白。
 */
const SRC_DIR = resolve(process.cwd(), 'src')

describe('normalizeComponentPath', () => {
  it('空值与纯空白归一化为空串', () => {
    expect(normalizeComponentPath(null)).toBe('')
    expect(normalizeComponentPath('')).toBe('')
    expect(normalizeComponentPath('   ')).toBe('')
  })

  it('能吃下后端写下的各种变体', () => {
    // 后端值由管理员维护，格式不可能被"约定"统一；兼容变体比要求后端改数据更现实。
    expect(normalizeComponentPath('/system/user')).toBe('system/user')
    expect(normalizeComponentPath('system/user')).toBe('system/user')
    expect(normalizeComponentPath('/system/user/index.vue')).toBe('system/user')
    expect(normalizeComponentPath('/SYSTEM/User.VUE')).toBe('system/user')
    expect(normalizeComponentPath(' /system/user ')).toBe('system/user')
  })
})

describe('resolveView', () => {
  it('空值与未知路径返回 null（不抛、不猜）', () => {
    expect(resolveView(null)).toBeNull()
    expect(resolveView('')).toBeNull()
    expect(resolveView('system/not-built')).toBeNull()
  })

  it('已知键返回组件工厂', () => {
    expect(resolveView('/system/user')).not.toBeNull()
    expect(resolveView('/system/trace')).not.toBeNull()
  })
})

describe('VIEW_REGISTRY 与视图文件的一致性', () => {
  /**
   * 每个键对应的视图文件。
   *
   * 这张表同时钉住两件事：
   * - 注册表里每一项都指向**真实存在**的文件（改名会红）；
   * - 注册表没有多出/少掉键（否则"契约里配了页面却白屏"不会被发现）。
   */
  const EXPECTATIONS: Array<{ key: string; file: string }> = [
    { key: 'system/user', file: 'views/system/UserListView.vue' },
    { key: 'system/department', file: 'views/system/DepartmentListView.vue' },
    { key: 'system/role', file: 'views/system/RoleListView.vue' },
    { key: 'system/permission', file: 'views/system/PermissionListView.vue' },
    { key: 'system/permission-resource', file: 'views/system/PermissionResourceListView.vue' },
    { key: 'system/session', file: 'views/system/SessionListView.vue' },
    { key: 'system/dictionary', file: 'views/system/DictionaryListView.vue' },
    { key: 'system/param', file: 'views/system/ParamListView.vue' },
    { key: 'system/audit-log', file: 'views/system/AuditLogListView.vue' },
    { key: 'system/trace', file: 'views/system/TraceListView.vue' },
  ]

  it('键集合与预期完全一致', () => {
    expect(Object.keys(VIEW_REGISTRY).sort()).toEqual(EXPECTATIONS.map((item) => item.key).sort())
  })

  it('每个键指向的视图文件都存在', () => {
    for (const { file } of EXPECTATIONS) {
      const target = `${SRC_DIR}/${file}`
      expect(() => readFileSync(target), `${file} 不存在`).not.toThrow()
    }
  })
})

describe('generateRoutes', () => {
  it('完整契约必须零 unresolved', () => {
    // 这是本文件最重要的一条断言：契约里有、本地没有组件 = 菜单点进去白屏。
    const result = generateRoutes(buildContract())
    expect(result.unresolved).toEqual([])
    expect(result.routes).toHaveLength(FULL_PAGE_SPECS.length)
  })

  it('meta.permission 用资源编码，meta.title 用页面名', () => {
    const result = generateRoutes(buildContract())
    const user = result.routes.find((route) => route.path === '/system/users')
    expect(user).toBeDefined()
    // 权限判定用 `code`：路由路径只是展示层，改名不影响判权。
    expect(user?.meta.permission).toBe('system:user:page')
    expect(user?.meta.title).toBe('用户管理')
  })

  it('component_path 缺失时记为 unresolved，不用 route_path 硬凑', () => {
    // 后端 CHECK 约束保证 PAGE 两者同非空；真出现 null 说明数据不完整，
    // 应当被"看得见"，而不是拿到一条指向错误组件的路由。
    const pages = [pageSpec('system:role:page', '/system/roles', null)]
    const result = generateRoutes(buildContract({ pages }))
    expect(result.routes).toEqual([])
    expect(result.unresolved).toEqual([
      { code: 'system:role:page', componentPath: null },
    ])
  })

  it('component_path 指向不存在的组件时进入 unresolved 且不生成路由', () => {
    const pages = [pageSpec('system:role:page', '/system/roles', '/system/nope')]
    const result = generateRoutes(buildContract({ pages }))
    expect(result.unresolved).toEqual([{ code: 'system:role:page', componentPath: '/system/nope' }])
    expect(result.routes).toEqual([])
  })

  it('route_path 为空的页面被跳过，不生成无名路由', () => {
    const pages = [pageSpec('system:role:page', '')]
    const result = generateRoutes(buildContract({ pages }))
    expect(result.routes).toEqual([])
  })

  it('重复 route_path 只保留第一条', () => {
    const pages = [pageSpec('a:page', '/dup'), pageSpec('b:page', '/dup')]
    const result = generateRoutes(buildContract({ pages }))
    expect(result.routes).toHaveLength(1)
    expect(result.routes[0]?.meta.permission).toBe('a:page')
  })

  it('路由名互不相同（同一 path 来自不同 code 时也要能区分）', () => {
    const result = generateRoutes(buildContract())
    const names = result.routes.map((route) => route.name)
    expect(new Set(names).size).toBe(names.length)
  })

  it('组件是 markRaw 过的原始对象，不是响应式代理', () => {
    const result = generateRoutes(buildContract())
    for (const route of result.routes) {
      // 组件一旦进入 reactive 代理就会丢失渲染上下文（表现为白屏但不报错）。
      expect(route.component).toBeTypeOf('object')
      expect(route.component).not.toBe('function')
    }
  })
})

describe('toRouteRecords', () => {
  it('输出 vue-router 单视图记录，不带 children', () => {
    const { routes } = generateRoutes(buildContract())
    const records = toRouteRecords(routes)
    expect(records).toHaveLength(routes.length)
    for (const record of records) {
      expect(record).not.toHaveProperty('children')
      expect(record.meta).toBeDefined()
      expect(typeof record.name).toBe('string')
    }
  })

  it('保持与生成器一致的顺序（菜单按顺序挂路由）', () => {
    const { routes } = generateRoutes(buildContract())
    const paths = toRouteRecords(routes).map((record) => record.path)
    expect(paths).toEqual(routes.map((route) => route.path))
  })
})

describe('契约驱动：菜单能点的页面一定进得了路由', () => {
  it('契约里的页面全部有对应路由', () => {
    const contract: PermissionContract = buildContract()
    const { routes, unresolved } = generateRoutes(contract)
    expect(unresolved).toEqual([])

    const routePaths = new Set(routes.map((route) => route.path))
    // 每一条菜单都能落到一条真实路由上；落不到就是"菜单有、点了没反应"。
    const menuPages = new Set<string>()
    for (const page of contract.pages) {
      if (page.route_path !== null && page.route_path !== '') menuPages.add(page.route_path)
    }
    for (const path of menuPages) {
      expect(routePaths.has(path), `${path} 没有对应路由`).toBe(true)
    }
  })
})
