import { defineStore } from 'pinia'
import type {
  PermissionResource,
  PermissionResourceUpdateRequest,
  PermissionStatus,
  ResourceType,
} from '@/types'
import type { ID } from '@/types/common'
import {
  createResource,
  deleteResource,
  listResources,
  updateResource,
} from '@/api/endpoints/resources'

/**
 * resourcesStore —— 权限资源（DD-20 / `08 §3`）。
 *
 * 资源是**权限的元数据**：没有它们就没有可授权的对象。它们被两个页面以两种
 * 方式读取：
 *
 * 1. 权限资源维护页 —— 分页 + 多维筛选（类型 / 状态 / 关键字）。
 * 2. 权限配置页 —— 按类型分组的**清单**，作为勾选授权的候选来源。
 *
 * 权限配置页用 `/admin/permission-resources` 而不是当前用户的权限契约，
 * 这一点是硬性的：被授权的角色可能持有当前管理员**看不到**的资源，
 * 拿契约当候选来源会静默丢掉它们（表现为"勾不上那个权限"）。
 *
 * 因此这里同样存两份：分页结果与分组清单，互不覆盖。
 */

/** 授权页要按类型分开取的候选清单。不是"资源类型全集"—— 菜单挂页面这类
 * 关系不属于授权勾选，没有单独取。 */
export type GrantableKind = 'PAGE' | 'MENU' | 'BUTTON' | 'API' | 'FIELD'

export const GRANTABLE_KINDS: GrantableKind[] = ['PAGE', 'MENU', 'BUTTON', 'API', 'FIELD']

/** 勾选授权用的清单，一次取回不分页。 */
export type GrantableCache = Record<GrantableKind, PermissionResource[]>

function emptyGrantable(): GrantableCache {
  return { PAGE: [], MENU: [], BUTTON: [], API: [], FIELD: [] }
}

/** 授权页每类资源取多少条。`GRANTABLE_LIMIT` 不是"分页大小"，详见 `ensureGrantable`。 */
const GRANTABLE_LIMIT = 100

export const useResourcesStore = defineStore('resources', {
  state: () => ({
    // ---- 分页列表（权限资源维护页） ----
    rows: [] as PermissionResource[],
    total: 0,
    pageNum: 1,
    pageSize: 20,
    loading: false,
    error: null as string | null,
    keyword: '',
    kindFilter: null as ResourceType | null,
    statusFilter: null as PermissionStatus | null,

    // ---- 分组清单（权限配置页的勾选候选） ----
    grantable: null as GrantableCache | null,
    grantableLoaded: false,
    grantableLoading: false,
    grantableError: null as string | null,
  }),

  getters: {
    /**
     * 是否可能有资源没进清单。
     *
     * 与角色清单同理：取回的数量**正好等于**上限时应当可疑。这时授权页的
     * 勾选框里会少掉一部分资源，而页面上没有任何提示，管理员只会觉得
     * "这个资源就是勾不上"。
     */
    grantableMightBeTruncated: (state): boolean => {
      if (state.grantable === null) return false
      return Object.values(state.grantable).some((list) => list.length >= GRANTABLE_LIMIT)
    },
  },

  actions: {
    async load(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const result = await listResources({
          pageNum: this.pageNum,
          pageSize: this.pageSize,
          resourceType: this.kindFilter,
          status: this.statusFilter,
          keyword: this.keyword === '' ? null : this.keyword,
        })
        this.rows = result.list
        this.total = result.total
        this.pageNum = result.pageNum
        this.pageSize = result.pageSize
      } catch (cause) {
        this.error = cause instanceof Error ? cause.message : '资源加载失败'
        this.rows = []
        this.total = 0
      } finally {
        this.loading = false
      }
    },

    /** 改筛选条件回到第 1 页。 */
    async setFilters(patch: {
      keyword?: string
      kind?: ResourceType | null
      status?: PermissionStatus | null
    }): Promise<void> {
      if (patch.keyword !== undefined) this.keyword = patch.keyword
      if (patch.kind !== undefined) this.kindFilter = patch.kind
      if (patch.status !== undefined) this.statusFilter = patch.status
      this.pageNum = 1
      await this.load()
    },

    async goToPage(pageNum: number, pageSize?: number): Promise<void> {
      this.pageNum = pageNum
      if (pageSize !== undefined) this.pageSize = pageSize
      await this.load()
    },

    /**
     * 取分组清单。已取过就不再发请求。
     *
     * 五类并行取：任何一类失败都不该让整个清单不可用 —— 授权页里
     * "API 那一列空着"会被误读成"该类别还没有资源"。失败的那类置空，
     * 其余四类照常可用，错误统一记在 `grantableError`。
     */
    async ensureGrantable(): Promise<void> {
      if (this.grantableLoaded) return
      this.grantableLoading = true
      this.grantableError = null
      try {
        const pages = await Promise.all(
          GRANTABLE_KINDS.map((kind) =>
            listResources({ pageNum: 1, pageSize: GRANTABLE_LIMIT, resourceType: kind }),
          ),
        )
        const next = emptyGrantable()
        GRANTABLE_KINDS.forEach((kind, index) => {
          next[kind] = pages[index]?.list ?? []
        })
        this.grantable = next
        this.grantableLoaded = true
      } catch (cause) {
        this.grantableError = cause instanceof Error ? cause.message : '资源清单加载失败'
        this.grantable = null
        this.grantableLoaded = false
      } finally {
        this.grantableLoading = false
      }
    },

    /** 资源增删改后调用：分页列表重拉，分组清单作废。 */
    invalidateGrantable(): void {
      this.grantableLoaded = false
    },

    async create(payload: Parameters<typeof createResource>[0]): Promise<PermissionResource> {
      const resource = await createResource(payload)
      this.invalidateGrantable()
      await this.load()
      return resource
    },

    /** 只发真正改动的字段（`undefined` 表示"没动"，由 endpoint 层过滤）。 */
    async update(
      resourceId: ID,
      payload: PermissionResourceUpdateRequest,
    ): Promise<PermissionResource> {
      const resource = await updateResource(resourceId, payload)
      this.invalidateGrantable()
      await this.load()
      return resource
    },

    async remove(resourceId: ID): Promise<void> {
      await deleteResource(resourceId)
      this.invalidateGrantable()
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
      this.kindFilter = null
      this.statusFilter = null
      this.grantable = null
      this.grantableLoaded = false
      this.grantableLoading = false
      this.grantableError = null
    },
  },
})
