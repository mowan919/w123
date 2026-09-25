import { http } from '../client'
import type { ID, PageResult } from '@/types/common'
import type {
  PermissionResource,
  PermissionResourceTreeNode,
  PermissionResourceUpdateRequest,
  PermissionStatus,
  ResourceType,
} from '@/types'

/**
 * 权限资源 CRUD（`08 §3` / DD-20）。
 *
 * ⚠️ `/tree` 必须声明在 `/{resource_id}` **之前**：FastAPI 按注册顺序匹配，
 * 反了的话 `tree` 会被当成 `resource_id` 解析成 422。
 */

export interface ResourceListQuery {
  pageNum: number
  pageSize: number
  resourceType?: ResourceType | null
  parentId?: ID | null
  status?: PermissionStatus | null
  keyword?: string | null
}

export function listResources(query: ResourceListQuery): Promise<PageResult<PermissionResource>> {
  return http.get<PageResult<PermissionResource>>('/admin/permission-resources', query)
}

/** 必须先于 `/{resource_id}`（见文件头说明）。 */
export function getResourceTree(query: Omit<ResourceListQuery, 'pageNum' | 'pageSize'>): Promise<
  PermissionResourceTreeNode[]
> {
  return http.get<PermissionResourceTreeNode[]>('/admin/permission-resources/tree', query)
}

export function createResource(payload: {
  resource_type: ResourceType
  resource_code: string
  resource_name: string
  parent_id?: ID | null
  sort_order?: number
  status?: PermissionStatus
  route_path?: string | null
  component_path?: string | null
  icon?: string | null
  api_method?: string | null
  api_path?: string | null
  field_key?: string | null
  owner_resource_id?: ID | null
}): Promise<PermissionResource> {
  return http.post<PermissionResource>('/admin/permission-resources', payload)
}

export function updateResource(
  resourceId: ID,
  payload: PermissionResourceUpdateRequest,
): Promise<PermissionResource> {
  const changed = Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined),
  )
  return http.put<PermissionResource>(`/admin/permission-resources/${resourceId}`, changed)
}

/** 删除是 `POST .../delete`（后端冻结的路径）。 */
export function deleteResource(resourceId: ID): Promise<void> {
  return http.post<void>(`/admin/permission-resources/${resourceId}/delete`)
}

/** 该菜单下挂了哪些页面。 */
export function getMenuPages(
  resourceId: ID,
): Promise<{ menu_id: ID; pages: PermissionResource[] }> {
  return http.get<{ menu_id: ID; pages: PermissionResource[] }>(
    `/admin/permission-resources/${resourceId}/pages`,
  )
}

export function setMenuPages(resourceId: ID, pageIds: ID[]): Promise<void> {
  return http.put<void>(`/admin/permission-resources/${resourceId}/pages`, { pageIds })
}
