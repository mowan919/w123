"""部门模型。

Frozen 依据
-----------
- Spec `07 §4` 表名 `departments`；字段 id / parent_id / department_code /
  department_name / status / created_at / updated_at / deleted_at。
- Spec `02 §1` 支持树形组织、查询子部门、部门管理员范围计算。
- Spec `07 §9` 要求 parent-child index、soft-delete-aware unique。
- Spec `00 §6` 默认逻辑删除；唯一约束必须考虑逻辑删除。

索引与约束设计
-------------
- `ix_departments_parent_id`：parent-child index（07 §9）。
- `uq_departments_department_code_active`：**partial unique index**，
  仅约束 `deleted_at IS NULL` 的行，从而允许"逻辑删除后以同一编码重建"。
- `ck_departments_parent_not_self`：禁止自我引用。

列长度说明：Spec 未定义字段长度，此处为 INTERIM 技术取值，
不表达任何业务规则；若后续 Spec 冻结长度需通过 migration 调整。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin
from app.db.types import enum_type
from app.models.enums import DepartmentStatus

if TYPE_CHECKING:
    from app.models.user import AdminUser


class Department(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """部门（树形组织节点）。"""

    __tablename__ = "departments"

    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="父部门 ID；NULL 表示根部门",
    )
    department_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="部门编码；逻辑删除感知唯一（partial unique index）",
    )
    department_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="部门名称",
    )
    status: Mapped[DepartmentStatus] = mapped_column(
        enum_type(DepartmentStatus),
        nullable=False,
        default=DepartmentStatus.ACTIVE,
        comment="部门状态 ACTIVE / DISABLED",
    )

    # 关系默认 lazy="raise"：异步下禁止隐式 IO，避免静默的 N+1 / MissingGreenlet。
    # 需要读取时必须显式 selectinload / joinedload。
    parent: Mapped[Department | None] = relationship(
        back_populates="children",
        remote_side="Department.id",
        lazy="raise",
    )
    children: Mapped[list[Department]] = relationship(
        back_populates="parent",
        lazy="raise",
    )
    users: Mapped[list[AdminUser]] = relationship(
        back_populates="department",
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_not_self"),
        Index(
            "uq_departments_department_code_active",
            "department_code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


__all__ = ["Department"]
