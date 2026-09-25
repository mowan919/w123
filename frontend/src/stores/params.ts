import { defineStore } from 'pinia'
import type {
  SystemParam,
  SystemParamCreateRequest,
  SystemParamStatus,
  SystemParamUpdateRequest,
} from '@/types'
import type { ID } from '@/types/common'
import {
  createSystemParam,
  deleteSystemParam,
  listSystemParams,
  updateSystemParam,
} from '@/api/endpoints/params'

/**
 * paramsStore —— 系统参数（`08 §9`）。
 *
 * 与字典是两套东西：字典是**枚举展示源**，参数是**运行期配置**（决定系统
 * 行为）。混用会导致"改一个下拉框的显示文案，顺带把某个开关打开了"。
 *
 * ⚠️ 一条不该被"顺手加个历史视图"的规则：**审计不记录参数值**。参数可能
 * 承载密钥类配置，而审计是 append-only、保留 2 年的。只要页面上能"看历史
 * 值"，就是一条不可撤回的泄漏通道。因此这个 store 只有当前值，没有历史。
 *
 * 这里只有一个消费页面，之所以仍然抽成 store，是为了把"改完必须重新加载"
 * 收进 store：新增 / 编辑 / 清空 / 删除这四处原来各写一遍 `await load()`，
 * 漏一处就会出现"改完列表不动"。
 */

export const useParamsStore = defineStore('params', {
  state: () => ({
    rows: [] as SystemParam[],
    total: 0,
    pageNum: 1,
    pageSize: 20,
    loading: false,
    error: null as string | null,
    /** 空串表示"不限"（`<select>` 的空选项 value 只能是空串）。 */
    keyword: '',
    statusFilter: '' as '' | 'ACTIVE' | 'DISABLED',
  }),

  actions: {
    async load(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const result = await listSystemParams({
          pageNum: this.pageNum,
          pageSize: this.pageSize,
          keyword: this.keyword === '' ? null : this.keyword,
          status: this.statusFilter === '' ? null : (this.statusFilter as SystemParamStatus),
        })
        this.rows = result.list
        this.total = result.total
        this.pageNum = result.pageNum
        this.pageSize = result.pageSize
      } catch (cause) {
        this.error = cause instanceof Error ? cause.message : '参数加载失败'
        this.rows = []
        this.total = 0
      } finally {
        this.loading = false
      }
    },

    async setFilters(patch: { keyword?: string; status?: '' | 'ACTIVE' | 'DISABLED' }): Promise<void> {
      if (patch.keyword !== undefined) this.keyword = patch.keyword
      if (patch.status !== undefined) this.statusFilter = patch.status
      this.pageNum = 1
      await this.load()
    },

    async goToPage(pageNum: number, pageSize?: number): Promise<void> {
      this.pageNum = pageNum
      if (pageSize !== undefined) this.pageSize = pageSize
      await this.load()
    },

    async create(payload: SystemParamCreateRequest): Promise<SystemParam> {
      const param = await createSystemParam(payload)
      await this.load()
      return param
    },

    async update(paramId: ID, payload: SystemParamUpdateRequest): Promise<SystemParam> {
      const param = await updateSystemParam(paramId, payload)
      await this.load()
      return param
    },

    /**
     * 清空当前值 → 回落到默认值。
     *
     * 这是一个**独立动作**，不是"把 `param_value` 改成空串"：
     * `clear_value` 与 `param_value` 互斥，后端会拒绝两者同时出现。
     * 调用方拿不到回显的实体，因此这里把改后的实体返回。
     */
    async clearValue(
      paramId: ID,
      keep: { param_name: string; description: string | null; status: SystemParamStatus },
    ): Promise<SystemParam> {
      const param = await updateSystemParam(paramId, {
        clear_value: true,
        param_name: keep.param_name,
        description: keep.description,
        status: keep.status,
      })
      await this.load()
      return param
    },

    async remove(paramId: ID): Promise<void> {
      await deleteSystemParam(paramId)
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
      this.statusFilter = ''
    },
  },
})
