import { defineStore } from 'pinia'
import type { Role, RoleCreateRequest, RoleUpdateRequest } from '@/types'
import type { ID } from '@/types/common'
import {
  createRole,
  deleteRole,
  listRoles,
  updateRole,
} from '@/api/endpoints/roles'

/**
 * rolesStore（`08 §7`）。
 *
 * 角色在这个应用里被**两种截然不同**的方式读取，所以这里存了两份：
 *
 * 1. `rows` / `total` / `pageNum` —— 角色管理页的**分页**结果，受筛选条件约束。
 * 2. `picker` —— 权限配置页角色下拉框要的**紧凑清单**（一次取回、不分页）。
 *
 * 把两者塞进同一个数组是整个 store 最容易踩的坑：角色管理页翻到第 3 页时，
 * 权限配置页的下拉框就会只剩第 3 页那几条；反过来，权限页"选中第一个角色"
 * 的逻辑也会把用户刚筛选出来的角色覆盖掉。分页状态属于列表，清单属于选择器，
 * 两者只能共存，不能合并。
 *
 * 写操作放在 store 里，是为了让"改完必须失效缓存"这件事**没有被忘掉的可能**：
 * 曾经每个页面的写法都是 `await api.x(); await load()`，漏一次就会出现
 * "新建的角色在别处还看不到"。
 */

/** 选择器一次取回多少条。`PICKER_LIMIT` 不是"分页大小"，详见 `ensurePicker`。 */
const PICKER_LIMIT = 100

export const useRolesStore = defineStore('roles', {
  state: () => ({
    // ---- 分页列表（角色管理页） ----
    rows: [] as Role[],
    total: 0,
    pageNum: 1,
    pageSize: 20,
    loading: false,
    error: null as string | null,
    /**
     * 筛选条件。
     *
     * `keyword` 与 `status` 用**空串**表示"不限"（`<select>` 的空选项 value
     * 只能是空串），发给接口时才转成 `null`。
     */
    keyword: '',
    status: '' as '' | 'ACTIVE' | 'DISABLED',

    // ---- 选择器清单（权限配置页） ----
    picker: [] as Role[],
    pickerLoaded: false,
    pickerLoading: false,
    pickerError: null as string | null,
  }),

  getters: {
    /**
     * 选择器是否已取满。
     *
     * `picker.length === PICKER_LIMIT` 应当**可疑**而不是"正好取完"：
     * 角色数超过上限时，清单里会静默少掉后面几条，管理员就再也选不到它们
     * —— 表现为"这个角色存在，但授权页的下拉框里没有"。这里把这个事实
     * 显式暴露出来，而不是让调用方去猜。
     */
    pickerMightBeTruncated: (state): boolean => state.picker.length >= PICKER_LIMIT,

    /** 按 id 取角色（权限配置页选中态回显用）。 */
    byId(state): Map<ID, Role> {
      return new Map([...state.rows, ...state.picker].map((role) => [role.id, role]))
    },
  },

  actions: {
    async load(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const result = await listRoles({
          pageNum: this.pageNum,
          pageSize: this.pageSize,
          keyword: this.keyword === '' ? null : this.keyword,
          status: this.status === '' ? null : this.status,
        })
        this.rows = result.list
        this.total = result.total
        this.pageNum = result.pageNum
        this.pageSize = result.pageSize
      } catch (cause) {
        this.error = cause instanceof Error ? cause.message : '角色加载失败'
        this.rows = []
        this.total = 0
      } finally {
        this.loading = false
      }
    },

    /** 改筛选条件回到第 1 页，否则会停在一个不存在的页码上。 */
    async setFilters(patch: { keyword?: string; status?: '' | 'ACTIVE' | 'DISABLED' }): Promise<void> {
      if (patch.keyword !== undefined) this.keyword = patch.keyword
      if (patch.status !== undefined) this.status = patch.status
      this.pageNum = 1
      await this.load()
    },

    async goToPage(pageNum: number, pageSize?: number): Promise<void> {
      this.pageNum = pageNum
      if (pageSize !== undefined) this.pageSize = pageSize
      await this.load()
    },

    /**
     * 取选择器清单。已取过就不再发请求。
     *
     * 失败时**把 `pickerLoaded` 置回 false**：这里没有"加载失败就别再试"的
     * 必要（它不像权限契约那样被路由守卫等待），留在 false 才能让下一次
     * 进来时重试，而不是让下拉框永远空着。
     */
    async ensurePicker(): Promise<void> {
      if (this.pickerLoaded) return
      this.pickerLoading = true
      this.pickerError = null
      try {
        const result = await listRoles({ pageNum: 1, pageSize: PICKER_LIMIT })
        this.picker = result.list
        this.pickerLoaded = true
      } catch (cause) {
        this.pickerError = cause instanceof Error ? cause.message : '角色清单加载失败'
        this.pickerLoaded = false
      } finally {
        this.pickerLoading = false
      }
    },

    /** 角色增减后调用：分页列表重拉，选择器清单作废。 */
    invalidatePicker(): void {
      this.pickerLoaded = false
    },

    async create(payload: RoleCreateRequest): Promise<Role> {
      const role = await createRole(payload)
      this.invalidatePicker()
      await this.load()
      return role
    },

    /**
     * 改角色。**只发真正改动的字段**：后端按 `model_fields_set` 分派，
     * 把没改的字段也带上会被当成"显式清空"（角色编码是只读的，必须排除）。
     */
    async update(roleId: ID, payload: RoleUpdateRequest): Promise<Role> {
      const role = await updateRole(roleId, payload)
      this.invalidatePicker()
      await this.load()
      return role
    },

    /** 删除是 `POST .../delete`（后端冻结的路径）。 */
    async remove(roleId: ID): Promise<void> {
      await deleteRole(roleId)
      this.invalidatePicker()
      await this.load()
    },

    reset(): void {
      this.rows = []
      this.total = 0
      this.pageNum = 1
      this.pageSize = 20
      this.loading = false
      this.error = null
      this.keyword = ''
      this.status = ''
      this.picker = []
      this.pickerLoaded = false
      this.pickerLoading = false
      this.pickerError = null
    },
  },
})
