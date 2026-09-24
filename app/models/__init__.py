"""ORM 模型注册入口。

**任何模型都必须在此处导入**，否则 `Base.metadata` 不会包含该表，
Alembic autogenerate 会漏表（Spec `13 §3` migration 必须完整可审查）。

Phase 2 注册的表：
    departments / admin_users / roles / user_roles / admin_user_password_histories

尚未注册（属后续 Phase 或未冻结）：
    sessions（Phase 5）、user_mfa（Phase 5）、role_inheritances（DD-05 未冻结）、
    role_permissions（CONFLICT-001 未关闭）、五类日志表（Phase 6，DD-08 未冻结）
"""

from __future__ import annotations

from app.models.department import Department
from app.models.enums import DepartmentStatus, RoleStatus, UserStatus
from app.models.password_history import AdminUserPasswordHistory
from app.models.role import Role, UserRole
from app.models.user import AdminUser

__all__ = [
    "AdminUser",
    "AdminUserPasswordHistory",
    "Department",
    "DepartmentStatus",
    "Role",
    "RoleStatus",
    "UserRole",
    "UserStatus",
]
