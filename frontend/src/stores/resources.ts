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
  getMenuPages,
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

/**
 * 取"菜单 → 挂载页面"映射时最多并行请求多少个菜单。
 *
 * 后端只有单菜单版本的 `GET /admin/permission-resources/{id}/pages`，
 * 没有批量端点，所以这里必然是一批并行请求。超过上限时**放弃加载**
 * 并置错：界面会退化成把页面统一放进「未挂载菜单的页面」分组，
 * 但**授权能力完好**（页面清单仍来自 grantable 缓存）。
 * 宁可少一层分组，也不要为了凑出层级而发明映射。
 */
const MENU_PAGES_MAX = 50

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

    // ---- 菜单 → 挂载页面（权限树的分组依据） ----
    menuPages: {} as Record<ID, ID[]>,
    menuPagesLoaded: false,
    menuPagesLoading: false,
    menuPagesError: null as string | null,
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

    /** 资源增删改后调用：分页列表重拉，分组清单与菜单映射一起作废。 */
    invalidateGrantable(): void {
      this.grantableLoaded = false
      // 菜单映射的键是资源 ID：资源一旦增删改（尤其是菜单与挂载关系），
      // 旧的映射可能指向已不存在的菜单或漏掉新页面。一起作废最省心，
      // 代价只是下一次进入权限配置页多发几个请求。
      this.menuPagesLoaded = false
    },

    /**
     * 取"菜单 → 挂载页面"映射（权限树的层级依据）。
     *
     * ⚠️ 这份数据只能来自后端 `menu_pages`（`GET .../{menu_id}/pages`）。
     * 曾经想过按资源编码的命名规律推（`system:user` ↔ `system:user:page`）：
     * 那样零请求、看着也"对"，但它把一份**约定**当成了事实 ——
     * 只要有一个页面不按这个规律编码，它在树上就会凭空消失，
     * 且没有任何报错。授权页最不该出现的就是"资源静默不见"。
     */
    async ensureMenuPages(): Promise<void> {
      if (this.menuPagesLoaded) return
      await this.ensureGrantable()
      const menus = this.grantable?.MENU ?? []
      // ⚠️ 清单没取到（`ensureGrantable` 失败）时，"没有菜单"不是结论：
      // 若在这里置 `menuPagesLoaded = true`，重试路径就被永久封死 ——
      // 网络恢复后再次进入权限配置页会直接 return，权限树永远缺层级，
      // 而界面上只有一次性的错误提示。宁可不置位，让下次调用重试。
      if (!this.grantableLoaded) {
        this.menuPages = {}
        this.menuPagesLoaded = false
        return
      }
      if (menus.length === 0) {
        this.menuPages = {}
        this.menuPagesLoaded = true
        return
      }
      if (menus.length > MENU_PAGES_MAX) {
        this.menuPages = {}
        this.menuPagesError = `菜单数量超过 ${MENU_PAGES_MAX}，本次未加载菜单层级；资源授权不受影响`
        this.menuPagesLoaded = false
        return
      }
      this.menuPagesLoading = true
      this.menuPagesError = null
      try {
        const results = await Promise.all(menus.map((menu) => getMenuPages(menu.id)))
        const next: Record<ID, ID[]> = {}
        for (const result of results) {
          // 返回 `{menu_id, pages}`：用**响应里的** menu_id 作键，
          // 而不是循环下标对应的 `menu.id` —— 两者不一致时（例如后端
          // 归一化了 ID），按请求参数索引会把页面挂到错误的菜单上。
          next[result.menu_id] = result.pages.map((page) => page.id)
        }
        this.menuPages = next
        this.menuPagesLoaded = true
      } catch (cause) {
        this.menuPagesError = cause instanceof Error ? cause.message : '菜单层级加载失败'
        this.menuPages = {}
        this.menuPagesLoaded = false
      } finally {
        this.menuPagesLoading = false
      }
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
      this.menuPages = {}
      this.menuPagesLoaded = false
      this.menuPagesLoading = false
      this.menuPagesError = null
    },
  },
})
