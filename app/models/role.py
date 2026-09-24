"""角色与用户-角色关联模型。

Frozen 依据
-----------
- Spec `07 §5` 核心表：`roles` / `user_roles` / `role_inheritances` / `role_permissions`。
- Spec `03 §2` Role 字段：id / role_code / role_name / status / description /
  created_at / updated_at / deleted_at。
- Spec `02 §4` / `03 §3`：用户可关联多个角色，有效权限为并集。

本 Phase 的范围边界（人类已裁定）
------------------------------
- **建 `roles` + `user_roles` 两张表**，为后续 Phase 保留正确的
  `User → UserRole → Role` 数据模型；
- **不实现** Role CRUD、权限授予、角色继承（属后续 Phase，且 CONFLICT-001
  未关闭）；
- **不建 `role_inheritances`**：其 SQL 存储模型属 `16 §34#5`
  （DD-05，UNRESOLVED DESIGN DECISION），未冻结前建表即为猜测；
- **不建 `role_permissions`**：权限资源定义 API 缺失（CONFLICT-001）。

`user_roles` 的删除语义说明（INTERIM 技术决策）
---------------------------------------------
关联表按**硬删除**处理（移除关联即删除该行），不含 `deleted_at`。
理由：关联行不是独立业务实体，而是两个实体的关系；为其引入软删除会让
唯一约束与"重新授予"语义复杂化，且 Spec `07 §3` 的 "可删除业务表" 指向
实体表。该决策已登记为 INTERIM，如后续 Spec 冻结关联表语义需调整。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin, utc_now
from app.db.types import enum_type
from app.models.enums import RoleStatus


class Role(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """角色。

    本 Phase 只建表与关联，不实现角色业务逻辑。
    """

    __tablename__ = "roles"

    role_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="角色编码；逻辑删除感知唯一",
    )
    role_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="角色名称",
    )
    status: Mapped[RoleStatus] = mapped_column(
        enum_type(RoleStatus),
        nullable=False,
        default=RoleStatus.ACTIVE,
        comment="角色状态 ACTIVE / DISABLED",
    )
    description: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="角色描述",
    )

    __table_args__ = (
        Index(
            "uq_roles_role_code_active",
            "role_code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class UserRole(Base):
    """用户-角色关联（多对多载体）。

    复合主键 `(user_id, role_id)` 天然保证同一用户不会重复持有同一角色，
    因此无需额外唯一索引。`role_id` 单独建索引以支持"按角色反查用户"。
    """

    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        primary_key=True,
        comment="用户 ID",
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("roles.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
        comment="角色 ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="授予时间 (UTC)",
    )


__all__ = ["Role", "UserRole"]
