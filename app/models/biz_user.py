"""统一业务用户域模型 —— V3.1 数据库设计基线（`02 统一业务用户域` + `08-DDL基线.sql`）。

Frozen 依据
-----------
- `08-DDL基线.sql` 的 Business User 段落（biz_user_level / biz_user /
  biz_user_profile / biz_user_login_identity / biz_user_session）是结构基线，
  本文件严格按基线落库。
- `02 统一业务用户域 §5~§7` 描述了登录日志 / 密码历史 / 验证记录三张表，
  但**未给出列定义**（DDL 基线未包含），其列结构属 INTERIM 技术推导，
  保持最小、可审查，等待冻结决策（见 `docs/DESIGN-DECISIONS.md §33`）。
- 本域表与系统管理域的 `admin_users` **完全分离**（设计原则 #1）：
  注册业务用户不得创建 sys_user，反之亦反。

状态列说明
----------
biz_user.status 等通用 status 列 DDL 仅给 DEFAULT 'ACTIVE'、未枚举取值域，
因此以普通 VARCHAR 落库（不发明 ACTIVE/DISABLED 等取值），取值域待冻结。
仅 `identity_type`（`02 §3` 显式枚举 USERNAME/EMAIL/PHONE）以枚举列落库。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin, utc_now
from app.db.types import enum_type
from app.models.enums import BizUserLoginIdentityType


class BizUserLevel(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """业务用户等级定义（`08-DDL基线.sql` / `03 用户成长中心 §8`）。

    `biz_user.user_level_id` 与 `biz_user_growth_account.current_level_id`
    均指向本表。本表放在业务用户域是因为 DDL 基线把它列在 Business User 段落。
    """

    __tablename__ = "biz_user_level"

    code: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="等级编码；逻辑删除感知唯一"
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="等级名称")
    level_value: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="等级数值；唯一，用于排序与判定"
    )
    required_growth_points: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="升级到该等级所需的成长值"
    )
    icon_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="等级图标 URL")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="等级描述")

    __table_args__ = (
        Index(
            "uq_biz_user_level_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_biz_user_level_value_active",
            "level_value",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class BizUser(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """业务用户（`08-DDL基线.sql` / `02 §1`）。

    与 `admin_users` 分离；注册业务用户只创建本表，不创建 sys_user。
    """

    __tablename__ = "biz_user"

    username: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="业务用户名；逻辑删除感知唯一"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )
    user_level_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_user_level.id", ondelete="RESTRICT"),
        nullable=True,
        comment="当前等级 ID",
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否必须修改初始口令"
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="口令最近修改时间 (UTC)"
    )
    password_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="口令过期时间 (UTC)"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近登录时间 (UTC)"
    )
    last_login_ip: Mapped[str | None] = mapped_column(INET, nullable=True, comment="最近登录 IP")

    __table_args__ = (
        Index(
            "uq_biz_user_username_active",
            "username",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class BizUserProfile(PrimaryKeyMixin, TimestampMixin, Base):
    """业务用户资料（`08-DDL基线.sql` / `02 §2`）。

    主键复用 `user_id`（一对一），无独立 id，也无逻辑删除（资料随用户走）。
    """

    __tablename__ = "biz_user_profile"

    user_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False, comment="业务用户 ID"
    )
    nickname: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="昵称")
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="头像 URL")
    bio: Mapped[str | None] = mapped_column(String(1000), nullable=True, comment="个人简介")
    gender: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="性别；取值域待冻结"
    )
    birthday: Mapped[date | None] = mapped_column(Date, nullable=True, comment="生日")


class BizUserLoginIdentity(PrimaryKeyMixin, TimestampMixin, Base):
    """业务用户登录身份（`08-DDL基线.sql` / `02 §3`）。

    用户名 / 邮箱 / 手机号等可登录标识，支持多身份与邮箱手机验证。
    """

    __tablename__ = "biz_user_login_identity"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        nullable=False,
        comment="所属业务用户 ID",
    )
    identity_type: Mapped[BizUserLoginIdentityType] = mapped_column(
        enum_type(BizUserLoginIdentityType, name="identity_type"),
        nullable=False,
        comment="身份类型 USERNAME / EMAIL / PHONE",
    )
    normalized_value: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="归一化后的身份值（小写 / 去格式）"
    )
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否已验证"
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否主身份"
    )

    __table_args__ = (
        UniqueConstraint(
            "identity_type",
            "normalized_value",
            name="uq_biz_user_login_identity_type_value",
        ),
    )


class BizUserSession(PrimaryKeyMixin, Base):
    """业务用户会话（`08-DDL基线.sql` / `02 §4`）。

    与 `sessions`（管理员会话）分离；业务侧无刷新令牌轮换等管理语义，
    因此只有会话元数据。无 created_at / updated_at（DDL 未定义）。
    """

    __tablename__ = "biz_user_session"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        nullable=False,
        comment="业务用户 ID",
    )
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="会话 ID；唯一")
    ip: Mapped[str | None] = mapped_column(INET, nullable=True, comment="登录 IP")
    user_agent: Mapped[str | None] = mapped_column(String(1000), nullable=True, comment="用户代理")
    login_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="登录时间 (UTC)"
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近活跃时间 (UTC)"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="过期时间 (UTC)"
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="撤销时间 (UTC)"
    )
    revoke_reason: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="撤销原因"
    )

    __table_args__ = (UniqueConstraint("session_id", name="uq_biz_user_session_id"),)


# ---------------------------------------------------------------------------
# 以下三张表 DDL 基线未给出列定义（`02 §5~§7` 仅文字描述），属 INTERIM 技术推导，
# 保持最小可审查结构，等待冻结决策（见 DESIGN-DECISIONS §33）。
# ---------------------------------------------------------------------------


class BizUserLoginLog(PrimaryKeyMixin, Base):
    """业务用户登录日志（`02 §5` 文字描述）。

    记录登录成功 / 失败；**不保存口令**。DDL 基线未定义列，本结构为最小推导。
    """

    __tablename__ = "biz_user_login_log"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        nullable=False,
        comment="业务用户 ID",
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="是否登录成功")
    fail_reason: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="失败原因")
    ip: Mapped[str | None] = mapped_column(INET, nullable=True, comment="登录 IP")
    user_agent: Mapped[str | None] = mapped_column(String(1000), nullable=True, comment="用户代理")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="创建时间 (UTC)",
    )


class BizUserPasswordHistory(PrimaryKeyMixin, TimestampMixin, Base):
    """业务用户口令历史（`02 §6` 文字描述）。

    保存历史 password hash，支持"最近 5 次禁止复用"（由应用层实现，表只存历史）。
    列结构镜像 `admin_user_password_histories`，DDL 基线未定义、属 INTERIM 推导。
    """

    __tablename__ = "biz_user_password_history"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        nullable=False,
        comment="业务用户 ID",
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="历史口令哈希")


class BizUserVerification(PrimaryKeyMixin, Base):
    """业务用户验证记录（`02 §7` 文字描述）。

    用于邮箱 / 手机 / 未来 MFA 等验证扩展。DDL 基线未定义列，属 INTERIM 推导。
    """

    __tablename__ = "biz_user_verification"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        nullable=False,
        comment="业务用户 ID",
    )
    identity_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="验证类型 EMAIL / PHONE / 等；取值域待冻结"
    )
    token_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="验证令牌哈希（不存明文令牌）"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="过期时间 (UTC)"
    )
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否已验证"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="创建时间 (UTC)",
    )


__all__ = [
    "BizUser",
    "BizUserLevel",
    "BizUserLoginIdentity",
    "BizUserLoginLog",
    "BizUserPasswordHistory",
    "BizUserProfile",
    "BizUserSession",
    "BizUserVerification",
]
