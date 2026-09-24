"""用户模型。

Frozen 依据
-----------
- Spec `07 §4` 表名 `admin_users`；字段 id / username / password_hash /
  display_name / phone / email / department_id / status / failed_login_count /
  locked_until / password_changed_at / must_change_password / created_at /
  updated_at / deleted_at。
- Spec `02 §2` 核心属性；`02 §3` 状态 ACTIVE / DISABLED / LOCKED。
- Spec `02 §5` 删除 = disable + logical delete；删除后不能通过普通查询返回。
- Spec `07 §9` soft-delete-aware unique（username）。
- Spec `10 §4` / `00 §8` password_hash 绝不返回、绝不记录。

字段命名说明：Spec 使用 `display_name`（非 real_name），本实现以 Spec 为准。

`password_hash` 由 `UserService` 通过 `app.core.security.password` 生成
（argon2id），业务代码不得直接写入。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin
from app.db.types import enum_type
from app.models.enums import UserStatus

if TYPE_CHECKING:
    from app.models.department import Department


class AdminUser(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """后台管理平台用户。"""

    __tablename__ = "admin_users"

    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="登录名；逻辑删除感知唯一（partial unique index）",
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="argon2id 哈希；绝不返回 API、绝不写入日志",
    )
    display_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="显示名称",
    )
    phone: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="手机号；日志与响应必须脱敏",
    )
    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="邮箱；日志与响应必须脱敏",
    )
    department_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="所属部门；数据范围计算的关键列",
    )
    status: Mapped[UserStatus] = mapped_column(
        enum_type(UserStatus),
        nullable=False,
        default=UserStatus.ACTIVE,
        comment="用户状态 ACTIVE / DISABLED / LOCKED；逻辑删除由 deleted_at 表达",
    )
    # 以下四个字段属于 Spec 00 §2 密码策略 / 10 §5 锁定策略的落地列。
    # Phase 2 只负责建列与写入，登录侧的行为在 Phase 4 实现。
    failed_login_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="连续登录失败次数；达到 5 次触发锁定",
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="锁定截止时间 (UTC)；NULL 表示未锁定",
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="上次改密时间 (UTC)；用于 90 天过期判断与历史校验",
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="管理员重置密码后置 True，首次登录必须改密",
    )

    department: Mapped[Department | None] = relationship(
        back_populates="users",
        lazy="raise",
    )

    __table_args__ = (
        Index(
            "uq_admin_users_username_active",
            "username",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


__all__ = ["AdminUser"]
