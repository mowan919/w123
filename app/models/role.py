"""角色与用户-角色关联模型。

Frozen 依据
-----------
- Spec `07 §5` 核心表：`roles` / `user_roles` / `role_inheritances` / `role_permissions`。
- Spec `03 §2` Role 字段：id / role_code / role_name / status / description /
  created_at / updated_at / deleted_at。
- Spec `02 §4` / `03 §3`：用户可关联多个角色，有效权限为并集。

范围边界（人类已裁定）
--------------------
Phase 2 交付：`roles` + `user_roles`（`User → UserRole → Role` 数据模型）。

Phase 3 追加：
- `roles.data_scope` 列 + `role_custom_scope_departments` 子表
  （**DD-07 已冻结**），用于 CUSTOM 数据范围的**真正持久化**；
- `role_inheritances`（**DD-05 已冻结，方案 A**）：邻接表表达的父子继承关系。

`role_permissions` / `role_field_permissions` / `permission_resources` /
`menu_pages` 定义在 `app.models.permission`（**DD-20 / DD-06 已冻结，方案 A**）。

`user_roles` 的删除语义说明（INTERIM 技术决策）
---------------------------------------------
关联表按**硬删除**处理（移除关联即删除该行），不含 `deleted_at`。
理由：关联行不是独立业务实体，而是两个实体的关系；为其引入软删除会让
唯一约束与"重新授予"语义复杂化，且 Spec `07 §3` 的 "可删除业务表" 指向
实体表。该决策已登记为 INTERIM，如后续 Spec 冻结关联表语义需调整。
同一口径适用于 `role_inheritances` / `role_permissions` /
`role_field_permissions` / `menu_pages`。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.scope import DataScope
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
    data_scope: Mapped[DataScope] = mapped_column(
        enum_type(DataScope, name="data_scope", length=32),
        nullable=False,
        default=DataScope.DEPARTMENT_CHILDREN,
        server_default=DataScope.DEPARTMENT_CHILDREN.value,
        comment="角色数据范围（Spec 03 §10）；默认 DEPARTMENT_CHILDREN（部门管理员默认值）",
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


class RoleInheritance(Base):
    """角色继承关系（DD-05 已冻结，方案 A：邻接表）。

    语义
    ----
    `child_role_id` **继承** `parent_role_id` 的权限：

    ```text
    child ──继承──▶ parent
    ```

    即有效权限 = 直接角色 ∪ 其全部祖先角色（`03 §4` / `00 §1#3` / `15 D-003`）。
    方向容易写反，故在列名上直接使用 `parent_role_id` / `child_role_id`
    而不是含义模糊的 `from/to`，并在展开 CTE 中显式注释。

    为什么用邻接表而不是闭包表
    ------------------------
    1. 本项目 `app/repositories/department.py` 已用递归 CTE 表达部门子树，
       角色继承沿用**同一模式**，维护者只需理解一种递归写法；
    2. Phase 3 规模下闭包表的读写维护成本（插入维护 N 行、删除需重建）
       换不到可观测收益；
    3. 环路的处理依赖"写入期检测 + 递归 CTE 用 `UNION`"二者配合，
       闭包表并不能免除写入期检测。

    `UNION`（非 `UNION ALL`）是**环路安全的最后一道防线**：
    即使写入期检测被绕过而库里出现环，展开查询也会自然收敛而非无限递归。
    """

    __tablename__ = "role_inheritances"

    parent_role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("roles.id", ondelete="RESTRICT"),
        primary_key=True,
        comment="被继承的角色 ID（权限提供方）",
    )
    child_role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("roles.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
        comment="继承的角色 ID（权限获得方）；单独建索引支持按子角色反查",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="继承关系建立时间 (UTC)",
    )

    __table_args__ = (
        # 禁止自环。这是三重环防护中最便宜的一道，放在数据库层兜底。
        CheckConstraint(
            "parent_role_id <> child_role_id",
            name="no_self_inheritance",
        ),
    )


class RoleCustomScopeDepartment(Base):
    """CUSTOM 数据范围的部门集合（DD-07 已冻结的持久化模型）。

    语义
    ----
    `roles.data_scope = CUSTOM` 时，本表存放该角色可见的**具体部门集合**。
    非 CUSTOM 的角色**不得**在本表留下残留行 —— 否则一旦某角色被改回
    CUSTOM，会静默继承过期数据，构成"权限放大"路径（Spec `11 §5`）。

    因此写入方（`RoleDataScopeService`）在非 CUSTOM 时必须清空本表。

    复合主键 `(role_id, department_id)` 天然去重，无需额外唯一索引；
    `department_id` 单独建索引以支持"按部门反查哪些角色可见它"。
    """

    __tablename__ = "role_custom_scope_departments"

    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("roles.id", ondelete="RESTRICT"),
        primary_key=True,
        comment="角色 ID",
    )
    department_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("departments.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
        comment="CUSTOM 范围内可见的部门 ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="写入时间 (UTC)",
    )


__all__ = ["Role", "RoleCustomScopeDepartment", "RoleInheritance", "UserRole"]
