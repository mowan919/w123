"""ORM 模型注册入口。

**任何模型都必须在此处导入**，否则 `Base.metadata` 不会包含该表，
Alembic autogenerate 会漏表（Spec `13 §3` migration 必须完整可审查）。

Phase 2 注册的表：
    departments / admin_users / roles / user_roles / admin_user_password_histories

Phase 3 追加（DD-05 / DD-06 / DD-07 / DD-19 / DD-20 均已冻结并落地）：
    - DD-07：`roles.data_scope` 列 + `role_custom_scope_departments`
    - DD-05：`role_inheritances`（邻接表 + 三重环路防护）
    - DD-20：`permission_resources` / `menu_pages` / `role_permissions`
    - DD-06：`role_field_permissions`（四级取值，最宽松者胜）
    - DD-04（仍为 INTERIM）：`permission_versions` —— 本表只提供**单调递增**的
      版本号；Redis Key 命名与缓存失效机制未冻结（Phase 9）。

Phase 4 追加（DD-02 / DD-03 **方案 A** 均已裁定并落地）：
    - DD-02：`sessions` / `session_refresh_token_history`
      —— 不透明令牌 + PG 唯一真源，**不引入** Redis（DD-03 留 Phase 9）。
      因此本 Phase 没有"Redis Key 命名"这一未冻结依赖。

尚未注册（属后续 Phase 或未冻结）：
    user_mfa（Phase 5，DD-01 具体 Provider 未冻结）、
    各日志表（Phase 6，DD-08 未冻结）
"""

from __future__ import annotations

from app.models.department import Department
from app.models.enums import (
    FIELD_ACCESS_READABLE,
    FIELD_ACCESS_WRITABLE,
    DepartmentStatus,
    FieldAccessLevel,
    HttpMethod,
    MfaStatus,
    PermissionResourceType,
    PermissionStatus,
    RefreshTokenRetirement,
    RoleStatus,
    SessionRevokeReason,
    UserStatus,
    most_permissive_field_level,
)
from app.models.password_history import AdminUserPasswordHistory
from app.models.permission import (
    MenuPage,
    PermissionResource,
    PermissionVersion,
    RoleFieldPermission,
    RolePermission,
)
from app.models.role import Role, RoleCustomScopeDepartment, RoleInheritance, UserRole
from app.models.session import SessionRefreshTokenHistory, UserSession
from app.models.user import AdminUser

__all__ = [
    "FIELD_ACCESS_READABLE",
    "FIELD_ACCESS_WRITABLE",
    "AdminUser",
    "AdminUserPasswordHistory",
    "Department",
    "DepartmentStatus",
    "FieldAccessLevel",
    "HttpMethod",
    "MenuPage",
    "MfaStatus",
    "PermissionResource",
    "PermissionResourceType",
    "PermissionStatus",
    "PermissionVersion",
    "RefreshTokenRetirement",
    "Role",
    "RoleCustomScopeDepartment",
    "RoleFieldPermission",
    "RoleInheritance",
    "RolePermission",
    "RoleStatus",
    "SessionRefreshTokenHistory",
    "SessionRevokeReason",
    "UserRole",
    "UserSession",
    "UserStatus",
    "most_permissive_field_level",
]
