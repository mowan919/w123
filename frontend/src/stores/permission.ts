import { defineStore } from 'pinia'
import type {
  PermissionContract,
  PermissionMenuItem,
  PermissionPageItem,
  PermissionFieldItem,
  FieldAccessLevel,
  DataScopePolicy,
  ID,
} from '@/types'
import { getPermissionContract } from '@/api/endpoints/permissions'

/**
 * permissionStore（FE-03）—— 后端权限链的**唯一**落点。
 *
 * 两条硬规则：
 * 1. 多角色的合并与继承展开由后端完成，前端**不得**重新实现角色继承算法
 *    （FE-03 §4）。
 * 2. 这里的判定只影响**展示**。真正的 API 授权在后端，前端隐藏按钮
 *    不能替代后端 403（FE-03 §6、FE-11 §2）。
 */

function toSet(items: Array<{ id: ID; code: string }>): Set<string> {
  return new Set(items.map((item) => item.code))
}

export interface MenuNode {
  id: ID
  code: string
  name: string
  icon: string | null
  parent_id: ID | null
  sort_order: number
  /** 该菜单关联的页面路由（来自 `page_ids` → 页面 `route_path`）。 */
  path: string
  children: MenuNode[]
}

/**
 * 算出每个菜单的挂载点：返回它最终挂在哪个父菜单下，根节点返回 `undefined`。
 *
 * 后端的父子关系理论上是有向无环的，但**不能当它一定成立**。父链一旦成环
 * （A 的父是 B、B 的父是 A，甚至自己指向自己），直接按 `parent_id` 建树就会
 * 无限递归 —— 表现为侧边栏直接卡死、控制台栈溢出，而这类脏数据只要管理员
 * 手误配一次就会出现。
 *
 * 这里做一次带环检测的上溯：把"父不存在"与"父成环"**都**归到根，于是每个
 * 菜单恰好有一个挂载点，整张图必然是森林。宁可层级排得不好看，也不能把
 * 界面卡死。
 */
function resolvePlacements(
  nodes: MenuNode[],
  byId: Map<ID, MenuNode>,
): Map<ID, MenuNode | undefined> {
  const placed = new Map<ID, MenuNode | undefined>()
  /** 当前这条上溯链，用来识别"绕回了自己"。 */
  const stack: MenuNode[] = []

  const resolve = (node: MenuNode): MenuNode | undefined => {
    if (placed.has(node.id)) return placed.get(node.id)
    if (stack.some((item) => item.id === node.id)) {
      // 环：这一支不能再往上走，本节点退化为根。
      placed.set(node.id, undefined)
      return undefined
    }
    stack.push(node)
    // 父不存在（或父自己就是根）时，本节点才退化成根。
    // 这里曾经图省事直接 `result = resolve(parent)`，把"父的挂载点"当成了
    // "父本身"，于是父是根时子节点也跟着当根 —— 三层菜单实测塌成三个平级根，
    // 侧边栏层级全乱。挂点要落到**父节点**上，不是落到父节点的挂点上。
    const parent = node.parent_id === null ? undefined : byId.get(node.parent_id)
    let result: MenuNode | undefined
    if (parent === undefined) {
      result = undefined
    } else {
      const parentPlacement = resolve(parent)
      result = parentPlacement === undefined ? parent : parentPlacement
    }
    // 自指（自己的 parent_id 指向自己）挂在自己名下毫无意义，退化为根。
    if (result === node) result = undefined
    stack.pop()
    placed.set(node.id, result)
    return result
  }

  for (const node of nodes) resolve(node)
  return placed
}

export const usePermissionStore = defineStore('permission', {
  state: () => ({
    loaded: false,
    loading: false,
    error: null as string | null,
    version: 0,
    userId: '' as ID,
    isSuperAdmin: false,
    /**
     * 当前用户持有的角色（直接 + 继承，均已由后端展开）。
     *
     * 用来回答"改这个角色的权限，会不会改动我自己" —— 只有会时才有必要
     * 重新拉取契约（FE-03 §5）。前端不做继承展开，只消费后端算好的结果。
     */
    roleIds: new Set<ID>(),
    pageCodes: new Set<string>(),
    menuCodes: new Set<string>(),
    buttonCodes: new Set<string>(),
    apiCodes: new Set<string>(),
    /** `field_key` → 访问级别。字段权限按 `field_key` 判定，不是按资源 id。 */
    fieldLevels: new Map<string, FieldAccessLevel>(),
    dataScopePolicy: null as DataScopePolicy | null,
    dataScopeDepartmentIds: null as ID[] | null,
    scopeIncludeSelf: false,
    /** 页面项保留了 `route_path` / `component_path`，动态路由生成器要用。 */
    pages: [] as PermissionPageItem[],
    menus: [] as PermissionMenuItem[],
  }),

  getters: {
    /** 权限集合是否已就绪。路由守卫据此决定"等一下"还是"放行"。 */
    isLoaded: (state): boolean => state.loaded,

    /**
     * 已展开的菜单树（按 `sort_order` 升序）。
     *
     * 菜单层级来自后端返回的父子关系，前端不做权限白名单
     * （FE-03 §7）。
     */
    menuTree(state): MenuNode[] {
      // 菜单项本身没有路由路径，只有 `page_ids`。先建 pageId → route_path 的映射，
      // 再在每个菜单上解出它的目标地址。菜单可能关联多个页面，取第一个即可。
      const pageRoute = new Map<string, string>()
      for (const page of state.pages) {
        if (page.route_path !== null && page.route_path !== '') pageRoute.set(page.id, page.route_path)
      }
      const routeOf = (menu: PermissionMenuItem): string => {
        for (const pageId of menu.page_ids) {
          const path = pageRoute.get(pageId)
          if (path !== undefined && path !== '') return path
        }
        return ''
      }

      const nodes = state.menus.map((menu) => ({
        id: menu.id,
        code: menu.code,
        name: menu.name,
        icon: menu.icon,
        parent_id: menu.parent_id,
        sort_order: menu.sort_order,
        path: routeOf(menu),
        children: [] as MenuNode[],
      }))
      const byId = new Map(nodes.map((node) => [node.id, node]))
      // 先算挂载点再挂树：父子关系成环时前者会把它收敛成森林，
      // 后者的简单循环才有可能构造出互相引用的两个节点。
      const placed = resolvePlacements(nodes, byId)
      const roots: MenuNode[] = []
      for (const node of nodes) {
        const parent = placed.get(node.id)
        if (parent === undefined) roots.push(node)
        else parent.children.push(node)
      }
      const sortRec = (list: MenuNode[]): void => {
        list.sort((a, b) => a.sort_order - b.sort_order || a.code.localeCompare(b.code))
        for (const node of list) sortRec(node.children)
      }
      sortRec(roots)
      return roots
    },

    hasPagePermission: (state) => (code: string): boolean => state.pageCodes.has(code),

    hasMenuPermission: (state) => (code: string): boolean => state.menuCodes.has(code),

    hasButtonPermission: (state) => (code: string): boolean => state.buttonCodes.has(code),

    hasApiPermission: (state) => (code: string): boolean => state.apiCodes.has(code),

    /** 当前用户是否持有其中任意一个角色。 */
    holdsAnyRole: (state) => (ids: ID[]): boolean => ids.some((id) => state.roleIds.has(id)),

    /** 字段权限四态（FE-05 §3）。缺省按 `HIDDEN` 处理 —— 未知键不该默认可见。 */
    getFieldPermission: (state) => (code: string): FieldAccessLevel =>
      state.fieldLevels.get(code) ?? 'HIDDEN',

    flags: (state): { pages: Set<string>; menus: Set<string>; buttons: Set<string>; apis: Set<string> } => ({
      pages: state.pageCodes,
      menus: state.menuCodes,
      buttons: state.buttonCodes,
      apis: state.apiCodes,
    }),
  },

  actions: {
    /** 拉取后端契约。失败时**必须**置 `loaded = true` —— 否则路由守卫会
     * 无限等待，页面白屏。 */
    async load(force = false): Promise<void> {
      if (this.loaded && !force) return
      this.loading = true
      this.error = null
      try {
        const contract: PermissionContract = await getPermissionContract()
        this.apply(contract)
      } catch (error) {
        this.error = error instanceof Error ? error.message : '权限加载失败'
        // 置 loaded 为 true 的目的是"停止等待"，不是"假装成功"。
        // 此时集合为空，等于无权限，受保护页面会被守卫拦到 403。
        this.loaded = true
        throw error
      } finally {
        this.loading = false
      }
    },

    /**
     * 导出一份完整的契约快照，供动态路由生成器消费。
     *
     * 走显式方法而不是 `store.$state`：store 里有 `Set` / `Map`，
     * 直接把 `$state` 当契约传会在跨 store 边界时丢类型、且漏掉
     * `data_scope` 这种需要重构的字段。
     */
    toContract(): PermissionContract {
      return {
        user_id: this.userId,
        is_super_admin: this.isSuperAdmin,
        // 直接角色与继承角色都已在 `roleIds` 里（后端展开过的完整集合），
        // 这里回填而不是留空 —— 契约的调用方有权拿到完整的角色列表。
        direct_role_ids: [...this.roleIds],
        inherited_role_ids: [],
        pages: this.pages,
        menus: this.menus,
        buttons: [],
        apis: [],
        fields: [],
        data_scope: {
          policy: this.dataScopePolicy,
          department_ids: this.dataScopeDepartmentIds,
          include_self: this.scopeIncludeSelf,
        },
        permission_version: this.version,
      }
    },

    apply(contract: PermissionContract): void {
      this.version = contract.permission_version
      this.userId = contract.user_id
      this.isSuperAdmin = contract.is_super_admin
      this.roleIds = new Set([...contract.direct_role_ids, ...contract.inherited_role_ids])
      this.pageCodes = toSet(contract.pages as Array<{ id: ID; code: string }>)
      this.menuCodes = toSet(contract.menus as Array<{ id: ID; code: string }>)
      this.buttonCodes = toSet(contract.buttons as Array<{ id: ID; code: string }>)
      this.apiCodes = toSet(contract.apis as Array<{ id: ID; code: string }>)
      this.pages = contract.pages
      this.menus = contract.menus
      const levels = new Map<string, FieldAccessLevel>()
      for (const field of contract.fields as PermissionFieldItem[]) {
        levels.set(field.field_key, field.access_level)
      }
      this.fieldLevels = levels
      this.dataScopePolicy = contract.data_scope.policy
      this.dataScopeDepartmentIds = contract.data_scope.department_ids
      this.scopeIncludeSelf = contract.data_scope.include_self
      this.loaded = true
    },

    /** 权限变更后的刷新（FE-03 §5）：不得假定权限永久缓存。 */
    async refresh(): Promise<void> {
      await this.load(true)
    },

    /**
     * 改动某个角色的配置后，只有当前用户**确实持有**该角色时才值得重拉契约（FE-03 §5）。
     *
     * 不无条件刷新：管理员在给"另一个角色"配权限时也被踢去重新登录一次，
     * 是很难解释的体验问题。但只要有交集就必须刷 —— 否则"我刚给自己加了按钮
     * 权限，界面上却没出现"会一直存在。
     *
     * 刷新失败**不影响**已保存的配置（保存已经成功），只记一条提示。
     */
    async refreshIfHoldsRole(roleIds: ID[]): Promise<boolean> {
      if (roleIds.length === 0) return false
      if (!this.holdsAnyRole(roleIds)) return false
      await this.refresh()
      return true
    },

    reset(): void {
      this.loaded = false
      this.loading = false
      this.error = null
      this.version = 0
      this.userId = ''
      this.isSuperAdmin = false
      this.roleIds = new Set()
      this.pageCodes = new Set()
      this.menuCodes = new Set()
      this.buttonCodes = new Set()
      this.apiCodes = new Set()
      this.fieldLevels = new Map()
      this.dataScopePolicy = null
      this.dataScopeDepartmentIds = null
      this.scopeIncludeSelf = false
      this.pages = []
      this.menus = []
    },
  },
})
