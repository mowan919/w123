import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import type { PermissionMenuItem, PermissionPageItem } from '@/types'
import { usePermissionStore } from '@/stores/permission'
import AppSidebar from '@/layouts/AppSidebar.vue'

/**
 * 侧栏（`FE-03 §7`）。
 *
 * 这里钉的是**导航结构里最容易悄悄坏掉的两件事**：
 *
 * 1. 顶级分组标题（`系统管理` / `日志管理`）**不导航**。它们可能没有任何
 *    关联页面，做成链接会跳到空路由；而只把 `@click` 挂在 div 上又拿不到
 *    键盘可达与 `aria-expanded`。所以它必须是 `<button>`。
 * 2. 分组可以**展开 / 收起**，且"我当前在哪一页"永远不会被折叠藏起来。
 */

/** 两个顶级分组：系统管理（2 项）与日志管理（2 项）—— 与库里的真实形状一致。 */
function pageFixture(
  id: string,
  code: string,
  name: string,
  routePath: string,
  sortOrder: number,
): PermissionPageItem {
  return {
    id,
    code,
    name,
    route_path: routePath,
    component_path: 'system/user',
    sort_order: sortOrder,
  }
}

function menuFixtures(): { pages: PermissionPageItem[]; menus: PermissionMenuItem[] } {
  const pages: PermissionPageItem[] = [
    pageFixture('p1', 'system:user:page', '用户管理', '/system/users', 10),
    pageFixture('p2', 'system:role:page', '角色管理', '/system/roles', 30),
    pageFixture('p9', 'system:audit-log:page', '审计日志', '/system/audit-logs', 90),
    pageFixture('p10', 'system:trace:page', '链路查询', '/system/traces', 100),
  ]

  const menus: PermissionMenuItem[] = [
    { id: 'm1', code: 'system:system', name: '系统管理', icon: 'setting', parent_id: null, sort_order: 10, page_ids: [] },
    { id: 'm2', code: 'system:user', name: '用户管理', icon: null, parent_id: 'm1', sort_order: 20, page_ids: ['p1'] },
    { id: 'm3', code: 'system:role', name: '角色管理', icon: null, parent_id: 'm1', sort_order: 30, page_ids: ['p2'] },
    // 「日志管理」是与「系统管理」平级的独立分组（迁移 `phase11_log_menu`）。
    { id: 'm9', code: 'log:manage', name: '日志管理', icon: 'log', parent_id: null, sort_order: 200, page_ids: [] },
    { id: 'm10', code: 'system:audit-log', name: '审计日志', icon: null, parent_id: 'm9', sort_order: 210, page_ids: ['p9'] },
    { id: 'm11', code: 'system:trace', name: '链路查询', icon: null, parent_id: 'm9', sort_order: 220, page_ids: ['p10'] },
  ]

  return { pages, menus }
}

/** 把页面塞进 store 的 `pages`、菜单塞进 `menus`（`menuTree` 由它们派生）。 */
function seedStore(): void {
  const store = usePermissionStore()
  const { pages, menus } = menuFixtures()
  store.pages = pages
  store.menus = menus
}

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', redirect: '/reports' },
      { path: '/reports', component: { template: '<div />' } },
      // 个人中心固定在侧栏底部，不来自权限契约；补一条路由免得 vue-router
      // 每次都打 "No match found" 的警告把真实失败埋掉。
      { path: '/profile', component: { template: '<div />' } },
      { path: '/system/users', component: { template: '<div />' } },
      { path: '/system/roles', component: { template: '<div />' } },
      { path: '/system/audit-logs', component: { template: '<div />' } },
      { path: '/system/traces', component: { template: '<div />' } },
    ],
  })
}

async function mountSidebar(path = '/reports'): Promise<{ wrapper: ReturnType<typeof mount>; router: Router }> {
  const router = makeRouter()
  await router.push(path)
  await router.isReady()
  const wrapper = mount(AppSidebar, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

/** 取某个分组标题（`<button>`）。 */
function groupTitle(wrapper: ReturnType<typeof mount>, name: string) {
  const found = wrapper
    .findAll('button.sidebar__group-title')
    .find((node) => node.text().includes(name))
  if (found === undefined) throw new Error(`没有找到分组标题「${name}」`)
  return found
}

/** 某个分组下当前渲染出来的子项文字。 */
function childrenText(wrapper: ReturnType<typeof mount>, name: string): string[] {
  const group = wrapper
    .findAll('.sidebar__group')
    .find((node) => node.find('.sidebar__group-title').text().includes(name))
  if (group === undefined) throw new Error(`没有找到分组「${name}」`)
  return group.findAll('.sidebar__item--child').map((node) => node.text())
}

beforeEach(() => {
  usePermissionStore().reset()
  seedStore()
})

describe('顶级分组标题', () => {
  it('是按钮而不是链接 —— 点了不导航', async () => {
    const { wrapper, router } = await mountSidebar('/reports')

    const title = groupTitle(wrapper, '系统管理')
    expect(title.element.tagName).toBe('BUTTON')
    // 分组本身没有关联页面（`page_ids` 为空），做成链接会跳到空路由。
    expect(wrapper.findAll('a').map((node) => node.text())).not.toContain('系统管理')
    expect(wrapper.findAll('a').map((node) => node.text())).not.toContain('日志管理')

    await title.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/reports')
  })

  it('带 aria-expanded，键盘与读屏都能知道当前是展开还是收起', async () => {
    const { wrapper } = await mountSidebar()

    const title = groupTitle(wrapper, '系统管理')
    expect(title.attributes('aria-expanded')).toBe('true')

    await title.trigger('click')
    expect(title.attributes('aria-expanded')).toBe('false')
  })

  it('默认展开：登录后第一眼要看得到有哪些页面', async () => {
    const { wrapper } = await mountSidebar()

    expect(childrenText(wrapper, '系统管理')).toEqual(['用户管理', '角色管理'])
    expect(childrenText(wrapper, '日志管理')).toEqual(['审计日志', '链路查询'])
  })

  it('点击能收起、再点能展开 —— 这就是"分组标题可点击"的全部语义', async () => {
    const { wrapper } = await mountSidebar()
    const title = groupTitle(wrapper, '系统管理')

    await title.trigger('click')
    expect(childrenText(wrapper, '系统管理')).toEqual([])

    await title.trigger('click')
    expect(childrenText(wrapper, '系统管理')).toEqual(['用户管理', '角色管理'])
  })

  it('收起一个分组不影响另一个', async () => {
    const { wrapper } = await mountSidebar()

    await groupTitle(wrapper, '系统管理').trigger('click')

    expect(childrenText(wrapper, '系统管理')).toEqual([])
    expect(childrenText(wrapper, '日志管理')).toEqual(['审计日志', '链路查询'])
  })
})

describe('当前所在的分组不会被折叠藏起来', () => {
  it('收起后从别处导航进来，自动重新展开', async () => {
    const { wrapper, router } = await mountSidebar('/reports')

    await groupTitle(wrapper, '日志管理').trigger('click')
    expect(childrenText(wrapper, '日志管理')).toEqual([])

    await router.push('/system/audit-logs')
    await flushPromises()

    // 否则"我在审计日志页，侧栏里却找不到它"，看起来像这一页不在菜单里。
    expect(childrenText(wrapper, '日志管理')).toEqual(['审计日志', '链路查询'])
    expect(groupTitle(wrapper, '日志管理').attributes('aria-expanded')).toBe('true')
  })
})

describe('两棵树并存', () => {
  it('日志不再是系统管理的子项', async () => {
    const { wrapper } = await mountSidebar()

    expect(childrenText(wrapper, '系统管理')).not.toContain('审计日志')
    expect(childrenText(wrapper, '系统管理')).not.toContain('链路查询')
    expect(childrenText(wrapper, '日志管理')).toEqual(['审计日志', '链路查询'])
  })

  it('根层顺序按 sort_order：系统管理在日志管理之前', async () => {
    const { wrapper } = await mountSidebar()

    const groups = wrapper.findAll('button.sidebar__group-title').map((node) => node.text())
    expect(groups).toEqual(['系统管理', '日志管理'])
  })
})

describe('没有菜单时', () => {
  it('给出空态而不是一片空白', async () => {
    usePermissionStore().reset()
    const { wrapper } = await mountSidebar()

    expect(wrapper.text()).toContain('没有可用菜单')
    expect(wrapper.findAll('button.sidebar__group-title')).toHaveLength(0)
  })
})
