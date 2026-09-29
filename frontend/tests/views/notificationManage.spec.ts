import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'

/**
 * 通知管理（`/system/notifications`，`DESIGN-DECISIONS §32`）。
 *
 * 这一页会产生**对外的、不可撤回**的影响：一条公告会扇出成 N 条收件箱行
 * （全员公告就是"每个活跃用户一条"）。因此这里的用例重点不在"渲染对不对"，
 * 而在**提交前挡住不该发出去的东西**，以及**发出去之后列表要与后端一致**。
 *
 * 三条容易静默做错的地方：
 *
 * 1. **受众选"指定角色"却没选角色**。后端有 CHECK 约束
 *    （`(audience_type='ROLE') = (audience_role_id IS NOT NULL)`），
 *    所以最终会被拒 —— 但用户拿到的是一个 422，而不是"请选择角色"。
 * 2. **切回"全体"时残留 roleId**。请求里带上一个角色 id 会被库层直接拒，
 *    而界面上受众明明显示的是"全体用户"。
 * 3. **发布后不回到第 1 页**。新公告排在最前（按 `created_at desc`），
 *    停在旧页码会让发布者刷新完看到一条自己的公告都没有 —— 看起来像没发成功。
 */

vi.mock('@/api/endpoints/notifications', () => ({
  listMyNotifications: vi.fn(),
  fetchUnreadCount: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
  listAnnouncements: vi.fn(),
  publishAnnouncement: vi.fn(),
  revokeAnnouncement: vi.fn(),
}))

vi.mock('@/api/endpoints/dictionaries', () => ({
  getPublicDict: vi.fn(),
}))

vi.mock('@/api/endpoints/roles', () => ({
  listRoles: vi.fn(),
  createRole: vi.fn(),
  updateRole: vi.fn(),
  deleteRole: vi.fn(),
}))

import * as notificationApi from '@/api/endpoints/notifications'
import * as dictApi from '@/api/endpoints/dictionaries'
import * as roleApi from '@/api/endpoints/roles'
import NotificationManageView from '@/views/system/NotificationManageView.vue'
import { useAppStore } from '@/stores/app'
import { usePermissionStore } from '@/stores/permission'
import type { Announcement, AnnouncementPage, Role } from '@/types'

const api = vi.mocked(notificationApi)
const dicts = vi.mocked(dictApi)
const roles = vi.mocked(roleApi)

const PUBLISH = 'notification:publish'
const REVOKE = 'notification:revoke'

function role(id: string, name: string): Role {
  return {
    id,
    role_code: `R-${id}`,
    role_name: name,
    description: null,
    status: 'ACTIVE',
    data_scope: 'ALL',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

function announcement(overrides: Partial<Announcement> = {}): Announcement {
  return {
    id: '910001',
    title: '系统维护通知',
    body: '本周六 02:00 起停机维护 2 小时。',
    level: 'IMPORTANT',
    audience_type: 'ALL',
    audience_role_id: null,
    recipient_count: 39,
    created_by_username: 'admin',
    created_at: '2026-09-29T06:00:00Z',
    ...overrides,
  }
}

function announcementPage(overrides: Partial<AnnouncementPage> = {}): AnnouncementPage {
  return { list: [announcement()], total: 1, pageNum: 1, pageSize: 20, ...overrides }
}

const mounted: VueWrapper[] = []

afterEach(() => {
  // 这一页 `attachTo: document.body`（弹窗要 teleport），
  // 不显式卸载会把整棵页面留在 body 上，下一个用例的文档级查询就会命中它 ——
  // 表现为"单独跑绿、全套跑红"。
  while (mounted.length > 0) mounted.pop()?.unmount()
})

async function mountView(): Promise<VueWrapper> {
  const wrapper = mount(NotificationManageView, { attachTo: document.body })
  mounted.push(wrapper)
  await flushPromises()
  await flushPromises()
  return wrapper
}

// ---------------------------------------------------------------- 弹窗交互
// 弹窗内容由 `NModal` teleport 到 body，`wrapper.find` 查不到，必须查文档。

function inModal(selector: string): HTMLElement[] {
  return Array.from(document.querySelectorAll(`.n-modal ${selector}`)) as HTMLElement[]
}

function modalText(): string {
  return Array.from(document.querySelectorAll('.n-modal'))
    .map((node) => node.textContent ?? '')
    .join(' ')
}

function modalButton(text: string): HTMLButtonElement {
  const found = Array.from(document.querySelectorAll('.n-modal button')).find((node) =>
    (node.textContent ?? '').includes(text),
  )
  if (found === undefined) throw new Error(`弹窗里找不到按钮：${text}`)
  return found as HTMLButtonElement
}

async function clickModalButton(text: string): Promise<void> {
  modalButton(text).dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await flushPromises()
  await flushPromises()
}

function writeField(element: HTMLElement, value: string): void {
  ;(element as HTMLInputElement).value = value
  element.dispatchEvent(new Event('input', { bubbles: true }))
  element.dispatchEvent(new Event('change', { bubbles: true }))
}

/**
 * 填一个字段并**等一轮渲染**。
 *
 * 这里不能省掉那个 `await`：表单的校验结果（`draftError`）是父组件算出来
 * 再作为 `error` **prop** 传给 `FormDialog` 的，而 prop 只在父组件重渲染时
 * 才刷新。填完立刻点提交，弹窗看到的还是上一帧的 `error`（"请填写标题"），
 * 于是**永远提交不出去** —— 表现为"填好了却提示必填"，与实现无关，
 * 纯粹是测试少了一拍。
 */
async function fill(element: HTMLElement, value: string): Promise<void> {
  writeField(element, value)
  await flushPromises()
}

function toolbarButton(wrapper: VueWrapper, text: string): HTMLButtonElement {
  const found = wrapper
    .findAll('button')
    .find((node) => (node.text() ?? '').includes(text))
  if (found === undefined) throw new Error(`找不到工具栏按钮：${text}`)
  return found.element as HTMLButtonElement
}

async function openPublish(wrapper: VueWrapper): Promise<void> {
  toolbarButton(wrapper, '发布公告').dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await flushPromises()
  await flushPromises()
}

/** 发布弹窗里的三个控件：标题 / 正文 / 下拉（level、audience，可能还有 role）。 */
function titleInput(): HTMLInputElement {
  const found = inModal('input')[0]
  if (found === undefined) throw new Error('找不到标题输入框')
  return found as HTMLInputElement
}

function bodyTextarea(): HTMLTextAreaElement {
  const found = inModal('textarea')[0]
  if (found === undefined) throw new Error('找不到正文输入框')
  return found as HTMLTextAreaElement
}

function selects(): HTMLSelectElement[] {
  return inModal('select') as HTMLSelectElement[]
}

function lastPublishPayload(): Record<string, unknown> {
  const call = api.publishAnnouncement.mock.calls.at(-1)
  if (call === undefined) throw new Error('没有发出发布请求')
  return call[0] as unknown as Record<string, unknown>
}

function lastAnnouncementQuery(): Record<string, unknown> | undefined {
  const call = api.listAnnouncements.mock.calls.at(-1)
  return call === undefined ? undefined : (call[0] as unknown as Record<string, unknown>)
}

beforeEach(() => {
  vi.clearAllMocks()

  api.listAnnouncements.mockResolvedValue(announcementPage())
  api.publishAnnouncement.mockResolvedValue({ announcement: announcement(), recipient_count: 39 })
  api.revokeAnnouncement.mockResolvedValue({ id: '910001', purged: 39 })
  dicts.getPublicDict.mockResolvedValue({
    dict_code: 'notification_level',
    dict_name: '通知轻重',
    description: null,
    items: [],
  })
  roles.listRoles.mockResolvedValue({
    list: [role('9001', '运维管理员'), role('9002', '客服')],
    total: 2,
    pageNum: 1,
    pageSize: 100,
  })

  // 两个按钮的权限位必须给上，否则 `PermissionButton` 直接不渲染，
  // 而报错会是"找不到按钮"这种与真实原因无关的现象。
  const permission = usePermissionStore()
  permission.reset()
  permission.buttonCodes = new Set([PUBLISH, REVOKE])
})

describe('列表', () => {
  it('首屏按默认分页拉取公告', async () => {
    await mountView()

    expect(lastAnnouncementQuery()).toMatchObject({ pageNum: 1, pageSize: 20 })
  })

  it('受众为"指定角色"时显示角色名，而不是裸 ID', async () => {
    api.listAnnouncements.mockResolvedValue(
      announcementPage({
        list: [announcement({ audience_type: 'ROLE', audience_role_id: '9001' })],
      }),
    )
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('指定角色')
    expect(wrapper.text()).toContain('运维管理员')
    // 只显示"指定角色"而不说哪个角色，看列表的人无法回答"这条是给谁的"。
    expect(wrapper.text()).not.toContain('9001')
  })

  it('角色已被删除时给出提示而不是留空', async () => {
    api.listAnnouncements.mockResolvedValue(
      announcementPage({
        list: [announcement({ audience_type: 'ROLE', audience_role_id: '999999' })],
      }),
    )
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('已删除角色')
  })

  it('空列表给出空态文案', async () => {
    api.listAnnouncements.mockResolvedValue(
      announcementPage({ list: [], total: 0 }),
    )
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('还没有发布过公告')
  })
})

describe('发布前挡住不该发出去的东西', () => {
  it('标题为空时不发请求，并说明缺什么', async () => {
    const wrapper = await mountView()
    await openPublish(wrapper)

    await clickModalButton('发布')

    expect(api.publishAnnouncement).not.toHaveBeenCalled()
    expect(modalText()).toContain('请填写标题')
  })

  it('受众选"指定角色"但没选角色时不发请求', async () => {
    const wrapper = await mountView()
    await openPublish(wrapper)
    await fill(titleInput(), '只给运维看')

    // 第 2 个下拉是受众。
    await fill(selects()[1]!, 'ROLE')

    await clickModalButton('发布')

    expect(api.publishAnnouncement).not.toHaveBeenCalled()
    expect(modalText()).toContain('请选择要接收公告的角色')
  })

  it('切回"全体用户"后角色选择框消失，不会带着残留的角色 id 提交', async () => {
    const wrapper = await mountView()
    await openPublish(wrapper)
    await fill(titleInput(), '标题')

    await fill(selects()[1]!, 'ROLE')
    // 选一个角色，制造出"残留"。
    await fill(selects()[2]!, '9001')
    expect(selects()).toHaveLength(3)

    await fill(selects()[1]!, 'ALL')
    expect(selects()).toHaveLength(2)

    await clickModalButton('发布')

    // 后端 CHECK 约束要求 `audience_type='ALL'` 时 role id 必须为 NULL；
    // 带着残留值会被库层直接拒掉，而界面上明明显示"全体用户"。
    expect(lastPublishPayload()['audience_type']).toBe('ALL')
    expect(lastPublishPayload()['audience_role_id']).toBeNull()
  })

  it('正文留空时提交 null 而不是空串', async () => {
    const wrapper = await mountView()
    await openPublish(wrapper)
    await fill(titleInput(), '只有标题')
    await fill(bodyTextarea(), '   ')

    await clickModalButton('发布')

    expect(lastPublishPayload()['body']).toBeNull()
  })
})

describe('发布后的列表与提示', () => {
  it('提交正确的负载，并按后端返回的收件人数给提示', async () => {
    api.publishAnnouncement.mockResolvedValue({
      announcement: announcement({ audience_type: 'ROLE', audience_role_id: '9001' }),
      recipient_count: 3,
    })
    const wrapper = await mountView()
    await openPublish(wrapper)

    await fill(titleInput(), '  系统维护通知  ')
    await fill(bodyTextarea(), '  本周六停机维护。  ')
    await fill(selects()[1]!, 'ROLE')
    await fill(selects()[2]!, '9001')

    await clickModalButton('发布')

    const payload = lastPublishPayload()
    // 首尾空格不能在提交时才由后端 trim：标题里的空格会影响列表观感，
    // 而且后端不做 trim 的话"标题为空"这类校验会漏过去。
    expect(payload['title']).toBe('系统维护通知')
    expect(payload['body']).toBe('本周六停机维护。')
    expect(payload['audience_type']).toBe('ROLE')
    expect(payload['audience_role_id']).toBe('9001')
    // 收件人数由后端统计（受数据范围与账号状态影响），前端猜不出来。
    expect(useAppStore().notice?.message).toContain('3')
  })

  it('发布后回到第 1 页并重查（新公告一定在最新一页）', async () => {
    api.listAnnouncements.mockImplementation(async (query) =>
      announcementPage({ total: 60, pageNum: query.pageNum, pageSize: query.pageSize }),
    )
    const wrapper = await mountView()

    // 先翻到第 3 页。
    const page3 = wrapper
      .findAll('.n-pagination-item')
      .find((node) => node.text().trim() === '3')
    expect(page3).toBeDefined()
    await page3!.trigger('click')
    await flushPromises()
    await flushPromises()
    expect(lastAnnouncementQuery()?.['pageNum']).toBe(3)

    await openPublish(wrapper)
    await fill(titleInput(), '新公告')
    await clickModalButton('发布')

    // 停在第 3 页会让发布者刷新完看不到自己的公告 —— 看起来像没发成功。
    expect(lastAnnouncementQuery()?.['pageNum']).toBe(1)
  })

  it('发布成功后弹窗关闭 —— 再次打开是干净的新表单', async () => {
    // 判据用"重新打开时表单是空的"，而不是去查弹窗 DOM 的可见性：
    // naive 的 Modal 关闭后节点仍留在文档里（只改 display），
    // 用可见性判断会把"其实没关"和"关了但节点还在"混成同一个结果。
    const wrapper = await mountView()
    await openPublish(wrapper)
    await fill(titleInput(), '标题')

    await clickModalButton('发布')

    // 先确认这一次真的发出去了 —— 否则下面的"表单是空的"会**恒真**
    // （即便发布被拦下，重开一次也是空表单），用例等于没写。
    expect(api.publishAnnouncement).toHaveBeenCalledTimes(1)

    await openPublish(wrapper)
    expect(titleInput().value).toBe('')
    expect(bodyTextarea().value).toBe('')
  })

  it('发布失败时把后端的原因原样告知，且弹窗保持打开（内容还在）', async () => {
    api.publishAnnouncement.mockRejectedValue(new Error('公告标题重复'))
    const wrapper = await mountView()
    await openPublish(wrapper)
    await fill(titleInput(), '标题')

    await clickModalButton('发布')

    expect(useAppStore().notice?.message).toBe('公告标题重复')
    expect(titleInput().value).toBe('标题')
  })
})

describe('撤回', () => {
  it('撤回要走确认，并说明会连同已读消息一起收回', async () => {
    const wrapper = await mountView()

    const revokeButton = wrapper
      .findAll('button')
      .find((node) => (node.text() ?? '').includes('撤回'))
    expect(revokeButton).toBeDefined()
    await revokeButton!.trigger('click')
    await flushPromises()

    // 确认框必须写清后果，不能只写"确定吗"。
    expect(modalText()).toContain('已经读过的')
    expect(api.revokeAnnouncement).not.toHaveBeenCalled()

    await clickModalButton('确认撤回')

    expect(api.revokeAnnouncement).toHaveBeenCalledWith('910001')
    expect(useAppStore().notice?.message).toContain('39')
  })

  it('撤回后重查列表', async () => {
    const wrapper = await mountView()
    const callsBefore = api.listAnnouncements.mock.calls.length

    await wrapper
      .findAll('button')
      .find((node) => (node.text() ?? '').includes('撤回'))!
      .trigger('click')
    await flushPromises()
    await clickModalButton('确认撤回')

    expect(api.listAnnouncements.mock.calls.length).toBeGreaterThan(callsBefore)
  })
})
