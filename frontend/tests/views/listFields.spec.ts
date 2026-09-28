import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { formatDateTime } from '@/utils/format'
import type { AuditLog } from '@/types'
import type { TraceEntry, TraceSummary } from '@/api/endpoints/logs'

/**
 * 「后端返回的字段要在界面上有去处」（需求 3）。
 *
 * 为什么值得单独一组用例
 * ----------------------
 * 漏用一个字段**不会报错**：`vue-tsc` 只看类型，后端也不会少发一个键，
 * 页面照常渲染 —— 只是那一列不存在。这类缺失在代码审查里几乎不可见
 * （要看出来得把响应 schema 与列定义逐字段对照），只能靠测试钉住。
 *
 * 断言方式刻意不是"文本里包含某个值"，而是**按表头定位单元格**：
 *
 * ```text
 * 取「锁定至」列 → 再看第一行那一格是什么
 * ```
 *
 * 这样同时钉住两件事：① 这一列存在；② 这一列绑的**是**这个字段。
 * 只断言"页面里出现过某个值"的话，列错位一格（值跑到隔壁列）照样能过。
 */

vi.mock('@/api/endpoints/organization', () => ({
  listUsers: vi.fn(),
  getUser: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  enableUser: vi.fn(),
  disableUser: vi.fn(),
  resetUserPassword: vi.fn(),
  getDepartmentTree: vi.fn(),
  createDepartment: vi.fn(),
  updateDepartment: vi.fn(),
  disableDepartment: vi.fn(),
  listSessions: vi.fn(),
  revokeSession: vi.fn(),
  listUserSessions: vi.fn(),
  revokeAllUserSessions: vi.fn(),
}))

vi.mock('@/api/endpoints/roles', () => ({
  listRoles: vi.fn(),
  createRole: vi.fn(),
  updateRole: vi.fn(),
  deleteRole: vi.fn(),
  getRolePermissions: vi.fn(),
  setRolePagePermissions: vi.fn(),
  setRoleMenuPermissions: vi.fn(),
  setRoleButtonPermissions: vi.fn(),
  setRoleApiPermissions: vi.fn(),
  setRoleFieldPermissions: vi.fn(),
  getRoleDataScope: vi.fn(),
  setRoleDataScope: vi.fn(),
}))

vi.mock('@/api/endpoints/dictionaries', () => ({
  getPublicDict: vi.fn(),
}))

vi.mock('@/api/endpoints/logs', () => ({
  listAuditLogs: vi.fn(),
  getAuditLog: vi.fn(),
  listTraces: vi.fn(),
  getTrace: vi.fn(),
}))

import * as orgApi from '@/api/endpoints/organization'
import * as rolesApi from '@/api/endpoints/roles'
import * as dictApi from '@/api/endpoints/dictionaries'
import * as logsApi from '@/api/endpoints/logs'
import UserListView from '@/views/system/UserListView.vue'
import SessionListView from '@/views/system/SessionListView.vue'
import AuditLogListView from '@/views/system/AuditLogListView.vue'
import TraceListView from '@/views/system/TraceListView.vue'
import { usePermissionStore } from '@/stores/permission'

const org = vi.mocked(orgApi)
const roles = vi.mocked(rolesApi)
const dicts = vi.mocked(dictApi)
const logs = vi.mocked(logsApi)

/**
 * 按表头定位单元格文字 —— 见文件头注释。
 *
 * 单元格里若有 `<input>`（手机号 / 邮箱是这样的），取它的 `value`：
 * `Element.text()` 对表单控件恒为空串，只看文本会把"值在输入框里"
 * 误判成"这一格没有内容"。
 */
function cellOf(wrapper: VueWrapper, title: string, rowIndex = 0): string {
  const headers = wrapper.findAll('thead th').map((node) => node.text())
  const index = headers.indexOf(title)
  if (index < 0) throw new Error(`表头里没有「${title}」列，实际有：${headers.join(' / ')}`)
  const row = wrapper.findAll('tbody tr')[rowIndex]
  if (row === undefined) throw new Error(`没有第 ${rowIndex} 行数据`)
  const cell = row.findAll('td')[index]
  if (cell === undefined) throw new Error(`第 ${rowIndex} 行没有第 ${index} 个单元格`)
  const inputs = cell.findAll('input')
  if (inputs.length > 0) {
    return inputs.map((node) => (node.element as HTMLInputElement).value).join(' ')
  }
  return cell.text()
}

function headersOf(wrapper: VueWrapper): string[] {
  return wrapper.findAll('thead th').map((node) => node.text())
}

async function mountView(component: unknown): Promise<VueWrapper> {
  const wrapper = mount(component as never)
  await flushPromises()
  await flushPromises()
  return wrapper
}

async function clickButton(wrapper: VueWrapper, text: string): Promise<void> {
  const button = wrapper.findAll('button').find((node) => node.text().includes(text))
  if (button === undefined) throw new Error(`找不到按钮：${text}`)
  await button.trigger('click')
  await flushPromises()
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()

  org.getDepartmentTree.mockResolvedValue([
    {
      id: '1002',
      parent_id: null,
      department_code: 'D002',
      department_name: '技术部',
      status: 'ACTIVE',
      children: [],
    },
  ])
  org.listUsers.mockImplementation(async (query) => ({
    list: [],
    total: 0,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }))
  org.listSessions.mockImplementation(async (query) => ({
    list: [],
    total: 0,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }))
  roles.listRoles.mockImplementation(async (query) => ({
    list: [],
    total: 0,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }))
  dicts.getPublicDict.mockResolvedValue({
    dict_code: 'user_status',
    dict_name: '用户状态',
    description: null,
    items: [
      {
        item_label: '启用',
        item_value: 'ACTIVE',
        item_code: 'active',
        sort_order: 10,
        is_default: true,
        description: null,
      },
      {
        item_label: '已锁定',
        item_value: 'LOCKED',
        item_code: 'locked',
        sort_order: 30,
        is_default: false,
        description: null,
      },
    ],
  })
  logs.listAuditLogs.mockImplementation(async (query) => ({
    list: [],
    total: 0,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }))
  logs.listTraces.mockImplementation(async (query) => ({
    list: [],
    total: 0,
    pageNum: query.pageNum,
    pageSize: query.pageSize,
  }))

  // 权限按钮默认 `mode="hide"`：不给授权就点不到「明细」。
  // 手机号 / 邮箱还受**字段权限**（FE-05 §3）约束，缺省 HIDDEN 不渲染 ——
  // 要断言这两列的内容，就得先把字段级别给上。
  const permission = usePermissionStore()
  permission.reset()
  permission.buttonCodes = new Set(['audit:read', 'trace:read'])
  permission.fieldLevels = new Map([
    ['phone', 'VISIBLE'],
    ['email', 'VISIBLE'],
    ['remark', 'READ_ONLY'],
    ['department_name', 'READ_ONLY'],
  ])
})

describe('用户管理页 —— `UserResponse` 的每个字段都有列', () => {
  const row = {
    id: '100000000000000001',
    username: 'alice',
    display_name: '爱丽丝',
    phone: '13100000001',
    email: 'alice@example.com',
    department_id: '1002',
    status: 'LOCKED' as const,
    failed_login_count: 3,
    locked_until: '2026-09-28T10:00:00Z',
    password_changed_at: '2026-09-01T08:00:00Z',
    must_change_password: true,
    created_at: '2026-08-01T08:00:00Z',
    updated_at: '2026-09-27T08:00:00Z',
  }

  beforeEach(() => {
    org.listUsers.mockResolvedValue({ list: [row], total: 1, pageNum: 1, pageSize: 20 })
  })

  it('13 个字段逐字段落到正确的列上', async () => {
    const wrapper = await mountView(UserListView)

    expect(cellOf(wrapper, '用户名')).toBe('alice')
    expect(cellOf(wrapper, '姓名')).toBe('爱丽丝')
    expect(cellOf(wrapper, '手机号')).toBe('13100000001')
    expect(cellOf(wrapper, '邮箱')).toBe('alice@example.com')
    // 部门显示的是名字，不是雪花 ID —— 但绑定错了就会漏出 1002。
    expect(cellOf(wrapper, '部门')).toBe('技术部')
    // 状态走字典翻译（`user_status`），不是直接怼枚举值。
    expect(cellOf(wrapper, '状态')).toBe('已锁定')
    expect(cellOf(wrapper, '需改密')).toBe('需改密')
    expect(cellOf(wrapper, '登录失败')).toBe('3')
    expect(cellOf(wrapper, '锁定至')).toBe(formatDateTime(row.locked_until))
    expect(cellOf(wrapper, '改密时间')).toBe(formatDateTime(row.password_changed_at))
    expect(cellOf(wrapper, '创建时间')).toBe(formatDateTime(row.created_at))
    expect(cellOf(wrapper, '更新时间')).toBe(formatDateTime(row.updated_at))
    expect(cellOf(wrapper, '用户 ID')).toBe(row.id)
  })

  it('未锁定 / 未改密的用户在这些列上是占位符，不是 undefined', async () => {    org.listUsers.mockResolvedValue({
      list: [
        {
          ...row,
          status: 'ACTIVE',
          must_change_password: false,
          failed_login_count: 0,
          locked_until: null,
          password_changed_at: null,
        },
      ],
      total: 1,
      pageNum: 1,
      pageSize: 20,
    })
    const wrapper = await mountView(UserListView)

    expect(cellOf(wrapper, '需改密')).toBe('否')
    expect(cellOf(wrapper, '登录失败')).toBe('0')
    expect(cellOf(wrapper, '锁定至')).toBe('—')
    expect(cellOf(wrapper, '改密时间')).toBe('—')
  })

  it('字段权限 HIDDEN 时联系方式不渲染 —— 列还在，格子里是空的', async () => {
    usePermissionStore().fieldLevels = new Map([
      ['phone', 'HIDDEN'],
      ['email', 'HIDDEN'],
    ])
    const wrapper = await mountView(UserListView)

    expect(cellOf(wrapper, '手机号')).toBe('')
    expect(cellOf(wrapper, '邮箱')).toBe('')
    // 与"字段没被列出来"区分开：列仍然在，只是没有内容。
    expect(headersOf(wrapper)).toContain('手机号')
  })

  it('字段权限的键是契约里的 `field_key`，不是 FIELD 资源的 `resource_code`', async () => {
    // 回归用例。曾经传 `'field:user.phone'` —— 契约下发的 `field_key` 是
    // `phone`（见 `scripts/seed_data.py` 的 FIELDS），前缀 `field:`
    // 与 `user.` 都不存在，于是查询恒为 HIDDEN：
    // **这两列对任何角色都是空白，包括超管**，且没有任何报错。
    const wrapper = await mountView(UserListView)

    expect(cellOf(wrapper, '手机号')).toBe(row.phone)
    expect(cellOf(wrapper, '邮箱')).toBe(row.email)

    // 反向确认：换成带前缀的键就又会变空 —— 说明这个断言真的在测键的拼写。
    usePermissionStore().fieldLevels = new Map([['field:user.phone', 'VISIBLE']])
    const broken = await mountView(UserListView)
    expect(cellOf(broken, '手机号')).toBe('')
  })
})

describe('会话管理页 —— `SessionResponse` 的每个字段都有列', () => {
  const row = {
    id: '200000000000000001',
    user_id: '100000000000000001',
    username: 'alice',
    display_name: '爱丽丝',
    login_at: '2026-09-28T01:00:00Z',
    last_active_at: '2026-09-28T02:00:00Z',
    ip: '10.0.0.9',
    user_agent: 'Mozilla/5.0 (Windows NT 10.0) Chrome/120',
    device: 'Windows / Chrome',
    access_expires_at: '2026-09-28T03:00:00Z',
    refresh_expires_at: '2026-10-05T01:00:00Z',
    revoked_at: '2026-09-28T02:30:00Z',
    revoke_reason: 'TOKEN_REUSE_DETECTED' as const,
    online: false,
  }

  beforeEach(() => {
    org.listSessions.mockResolvedValue({ list: [row], total: 1, pageNum: 1, pageSize: 20 })
  })

  it('会话 ID / 用户 ID / 两个过期时间 / 撤销原因全部可见', async () => {
    const wrapper = await mountView(SessionListView)

    expect(cellOf(wrapper, '会话 ID')).toBe(row.id)
    expect(cellOf(wrapper, '用户 ID')).toBe(row.user_id)
    expect(cellOf(wrapper, 'Access 过期')).toBe(formatDateTime(row.access_expires_at))
    expect(cellOf(wrapper, '会话上限')).toBe(formatDateTime(row.refresh_expires_at))
    expect(cellOf(wrapper, '撤销时间')).toBe(formatDateTime(row.revoked_at))
  })

  it('撤销原因译成中文，且令牌复用被单独标红（安全事件不该混在普通撤销里）', async () => {
    const wrapper = await mountView(SessionListView)

    const cell = cellOf(wrapper, '撤销原因')
    expect(cell).toBe('令牌复用')
    const tag = wrapper.findAll('tbody td')[headersOf(wrapper).indexOf('撤销原因')]
    expect(tag?.find('.tag--locked').exists()).toBe(true)
  })

  it('用户名格里同时给出显示名与登录名，设备格里同时给出粗分类与原始 UA', async () => {
    const wrapper = await mountView(SessionListView)

    expect(cellOf(wrapper, '用户')).toContain('爱丽丝')
    expect(cellOf(wrapper, '用户')).toContain('alice')
    expect(cellOf(wrapper, '设备')).toContain('Windows / Chrome')
    expect(cellOf(wrapper, '设备')).toContain('Chrome/120')
  })

  it('未撤销的会话：撤销时间与原因都是占位符', async () => {
    org.listSessions.mockResolvedValue({
      list: [{ ...row, revoked_at: null, revoke_reason: null, online: true }],
      total: 1,
      pageNum: 1,
      pageSize: 20,
    })
    const wrapper = await mountView(SessionListView)

    expect(cellOf(wrapper, '状态')).toBe('在线')
    expect(cellOf(wrapper, '撤销时间')).toBe('—')
    expect(cellOf(wrapper, '撤销原因')).toBe('—')
  })
})

describe('审计日志页 —— `AuditLogResponse` 的每个字段都有去处', () => {
  const row: AuditLog = {
    id: '300000000000000001',
    trace_id: 'trace-abc',
    request_id: 'req-xyz',
    operator_id: '100000000000000001',
    operator_username: 'alice',
    action: 'USER_DISABLE',
    resource_type: 'USER',
    resource_id: '100000000000000009',
    before_data: { status: 'ACTIVE' },
    after_data: { status: 'DISABLED' },
    result: 'FAILURE',
    error_code: 409001,
    ip: '10.0.0.9',
    user_agent: 'curl/8.4.0',
    created_at: '2026-09-28T02:00:00Z',
  }

  beforeEach(() => {
    logs.listAuditLogs.mockResolvedValue({ list: [row], total: 1, pageNum: 1, pageSize: 20 })
    logs.getAuditLog.mockResolvedValue(row)
  })

  it('列表里能看到追踪 ID / 请求 ID / 错误码 / 客户端 / 操作者 ID', async () => {
    const wrapper = await mountView(AuditLogListView)

    expect(cellOf(wrapper, '日志 ID')).toBe(row.id)
    expect(cellOf(wrapper, '追踪 ID')).toBe('trace-abc')
    expect(cellOf(wrapper, '请求 ID')).toBe('req-xyz')
    expect(cellOf(wrapper, '操作者 ID')).toBe(row.operator_id)
    expect(cellOf(wrapper, '错误码')).toBe('409001')
    expect(cellOf(wrapper, '客户端')).toBe('curl/8.4.0')
    expect(cellOf(wrapper, '结果')).toBe('FAILURE')
  })

  it('成功的记录错误码列是占位符（0 与"没有错误码"是两回事）', async () => {
    logs.listAuditLogs.mockResolvedValue({
      list: [{ ...row, result: 'SUCCESS', error_code: null }],
      total: 1,
      pageNum: 1,
      pageSize: 20,
    })
    const wrapper = await mountView(AuditLogListView)

    expect(cellOf(wrapper, '错误码')).toBe('—')
  })

  it('明细抽屉给出变更前后与客户端 —— 这两项在列表里放不下', async () => {
    const wrapper = await mountView(AuditLogListView)
    await clickButton(wrapper, '明细')

    const text = wrapper.find('.drawer').text()
    expect(text).toContain('curl/8.4.0')
    expect(text).toContain('ACTIVE')
    expect(text).toContain('DISABLED')
    expect(text).toContain(row.id)
    // 时间是展示层格式化的，不是裸 ISO 串。
    expect(text).toContain(formatDateTime(row.created_at))
  })
})

describe('链路查询页 —— `TraceSummary` / `TraceEntry` 的每个字段都有去处', () => {
  const summary: TraceSummary = {
    trace_id: 'trace-abc',
    request_id: 'req-xyz',
    first_seen_at: '2026-09-28T02:00:00Z',
    last_seen_at: '2026-09-28T02:00:01Z',
    counts: { access: 1, audit: 1 },
    total_entries: 2,
  }

  const entries: TraceEntry[] = [
    {
      log_type: 'access',
      id: '400000000000000001',
      trace_id: 'trace-abc',
      request_id: 'req-xyz',
      created_at: '2026-09-28T02:00:00Z',
      operator_id: '100000000000000001',
      operator_username: 'alice',
      name: 'GET /admin/users',
      result: 'SUCCESS',
      detail: { status_code: 200 },
    },
  ]

  beforeEach(() => {
    logs.listTraces.mockResolvedValue({ list: [summary], total: 1, pageNum: 1, pageSize: 20 })
    logs.getTrace.mockResolvedValue({ trace_id: summary.trace_id, entries })
  })

  it('列表里能看到请求 ID（此前只有链路 ID）', async () => {
    const wrapper = await mountView(TraceListView)

    expect(cellOf(wrapper, '链路 ID')).toBe('trace-abc')
    expect(cellOf(wrapper, '请求 ID')).toBe('req-xyz')
    expect(cellOf(wrapper, '首条时间')).toContain(formatDateTime(summary.first_seen_at))
    expect(cellOf(wrapper, '日志类型分布')).toContain('access×1')
    expect(cellOf(wrapper, '总条数')).toBe('2')
  })

  it('明细里给出链路 ID、条目 ID、操作者与请求 ID', async () => {
    const wrapper = await mountView(TraceListView)
    await clickButton(wrapper, '明细')

    const drawer = wrapper.find('.drawer').text()
    expect(drawer).toContain('trace-abc')
    expect(drawer).toContain(entries[0]?.id)
    expect(drawer).toContain('alice')
    expect(drawer).toContain('100000000000000001')
    expect(drawer).toContain('req-xyz')
    expect(drawer).toContain('status_code')
  })
})
