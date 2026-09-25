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

Phase 5 追加（DD-22 / DD-23 / DD-24 **方案 A** 已按裁定草案落地）：
    - DD-24：`mfa_policies`（策略，作用主体 USER / ROLE，`required` 可空以区分
      "未表态"与"明确不要求"）、`user_mfa`（凭据，唯一键含 provider 以支持迁移并存）、
      `mfa_challenges`（DD-23 的一次性挑战，只存令牌哈希）
    - **仍未冻结**：V1 具体 Provider（`00 §4` / `16 §1`）—— 因此本项目的 `app/`
      下不存在任何具体算法实现，Phase 5 只交付 Provider-无关的骨架。

Phase 6 追加（DD-08 日志分区仍**未冻结**，故采用技术默认并登记 INTERIM）：
    - `audit_logs` / `security_logs` / `operation_logs` / `access_logs` /
      `application_logs` —— `06 §1` 的五类日志。
    - **未冻结**：`DD-08` 日志**分区**（PostgreSQL 声明式分区 / pg_partman /
      归档到对象存储）。本 Phase 交付**不分区**的表 + 保留期清理能力；
      分区与归档延后到日志量真正需要时（`06 §5` 只要求"**提供**后续归档/清理能力"）。
    - 五张表一律只保留 `created_at`（**无 `updated_at`**），
      并由迁移中的 `BEFORE UPDATE` 触发器强制拒绝更新 —— `10 §8` append-only。

Phase 7 追加（Spec `05 §1`~`§3` 冻结字典模型；系统参数表名与端点**未冻结**）：
    - `sys_dict_type` / `sys_dict_item`：两个冻结表名来自 `05 §2` / `05 §3`，
      含 `05 §3` 要求的"同字典 `item_value` 软删除感知唯一"。
    - `sys_params`：`05 §5` 只规定"参数必须有类型 / 默认值 / 状态 / 描述"，
      **未命名表**。表名 `sys_params` 属 INTERIM-7-01（对 `05 §2` 命名惯例的
      最小推导），端点属 INTERIM-7-04。字典与系统参数**分表、分服务、分端点**
      （`05 §5` 第一句 + `PHASE-007-DICTIONARY.md`）。
"""

from __future__ import annotations

from app.models.department import Department
from app.models.dict import SysDictItem, SysDictType
from app.models.enums import (
    FIELD_ACCESS_READABLE,
    FIELD_ACCESS_WRITABLE,
    DepartmentStatus,
    DictStatus,
    FieldAccessLevel,
    HttpMethod,
    MfaPolicySubject,
    MfaStatus,
    PermissionResourceType,
    PermissionStatus,
    RefreshTokenRetirement,
    RoleStatus,
    SessionRevokeReason,
    SystemParamStatus,
    SystemParamType,
    UserStatus,
    most_permissive_field_level,
)
from app.models.logs import (
    LOG_MODELS,
    AccessLog,
    ApplicationLog,
    AuditLog,
    LogModel,
    OperationLog,
    SecurityLog,
)
from app.models.mfa import MfaChallenge, MfaPolicy, UserMfa
from app.models.param import SysParam
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
    "LOG_MODELS",
    "AccessLog",
    "AdminUser",
    "AdminUserPasswordHistory",
    "ApplicationLog",
    "AuditLog",
    "Department",
    "DepartmentStatus",
    "DictStatus",
    "FieldAccessLevel",
    "HttpMethod",
    "LogModel",
    "MenuPage",
    "MfaChallenge",
    "MfaPolicy",
    "MfaPolicySubject",
    "MfaStatus",
    "OperationLog",
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
    "SecurityLog",
    "SessionRefreshTokenHistory",
    "SessionRevokeReason",
    "SysDictItem",
    "SysDictType",
    "SysParam",
    "SystemParamStatus",
    "SystemParamType",
    "UserMfa",
    "UserRole",
    "UserSession",
    "UserStatus",
    "most_permissive_field_level",
]
