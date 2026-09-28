/** 类型统一出口。分层约定：View → Component → Store → API Client → Backend。 */

export type { ID, DateTime, ApiEnvelope, PageParams, PageResult, OptionLike } from './common'
export type {
  LoginRequest,
  LoginResponse,
  LoginMfaRequiredResponse,
  RefreshRequest,
  ChangePasswordRequest,
  MfaVerifyResponse,
  TokenPair,
  AuthUser,
  LogoutResponse,
  MeResponse,
  MfaCodeRequest,
  MfaVerifyRequest,
  MfaSetupResponse,
  MfaActionResponse,
  MfaStatusResponse,
} from './auth'
export type {
  PermissionPageItem,
  PermissionMenuItem,
  PermissionButtonItem,
  PermissionApiItem,
  PermissionFieldItem,
  PermissionDataScope,
  DataScopePolicy,
  FieldAccessLevel,
  ResourceType,
  PermissionContract,
  RolePermissionView,
  PermissionResource,
  PermissionResourceTreeNode,
} from './permission'
export type {
  User,
  UserPage,
  UserCreateRequest,
  UserUpdateRequest,
  UserResetPasswordRequest,
  UserListQuery,
  Department,
  DepartmentTreeNode,
  DepartmentCreateRequest,
  DepartmentUpdateRequest,
  RoleSummary,
} from './organization'
export type { Session, SessionPage } from './session'
export type { Role, RolePage, RoleCreateRequest, RoleUpdateRequest, RoleDataScope, RoleFieldPermissionItem } from './role'
export type { PermissionResourceUpdateRequest, PermissionStatus } from './permission'
/**
 * 例外：下面这两个是**运行时常量**，不是类型。
 *
 * 放在与 `GrantKind` 同一个文件里，是为了让"四类二元权限"这个概念
 * 只有一处定义 —— 顺序数组与中文名散落到各个视图里，
 * 迟早出现"权限树列了四类、提交时只提交三类"这种不报错的缺失。
 */
export { GRANT_KINDS, GRANT_KIND_LABEL, emptySelection } from './permission'
export type { GrantKind, GrantSelection } from './permission'
export type {
  DictType,
  DictTypePage,
  DictTypeCreateRequest,
  DictTypeUpdateRequest,
  DictTypeDeleteResult,
  DictItem,
  DictItemList,
  DictItemCreateRequest,
  DictItemUpdateRequest,
  DictStatus,
  PublicDictItem,
  PublicDictResponse,
} from './dict'
export type {
  SystemParam,
  SystemParamPage,
  SystemParamCreateRequest,
  SystemParamUpdateRequest,
  SystemParamStatus,
} from './param'
export type { AuditLog, AuditLogPage } from './log'
