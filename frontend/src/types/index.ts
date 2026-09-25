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
