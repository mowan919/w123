"""Tools 工具域模型 —— V3.1 数据库设计基线（`04 Tools 工具域` + `08-DDL基线.sql`）。

Frozen 依据
-----------
- `08-DDL基线.sql` 的 Tools 段落是结构基线，本文件严格按基线落库。
- `04 §4`：`component_key` 映射到受控实现，管理员**不得**填写任意 Vue import path。
- `04 §10`：游客 / 用户额度与限流走 Redis（key 结构待冻结，不由本文件建模）。

状态 / 类型列说明
----------------
- `execution_mode`（`04 §2` 显式 FRONTEND/BACKEND/ASYNC）、`lifecycle_status`
  （DRAFT/TESTING/ACTIVE/DISABLED）、`subject_type`（GUEST/USER_LEVEL）
  以枚举列落库（`app/models/enums.py`）。
- `visibility`（仅 DEFAULT 'PUBLIC'）、`result`、`component_type`、`tool_version.status`
  等未枚举取值域，以普通 VARCHAR 落库，取值域待冻结。
- 工具使用统计与工具执行**解耦**（`04 §11`）：本域只存统计聚合，不存执行输入。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin, utc_now
from app.db.types import enum_type
from app.models.enums import (
    ToolAccessSubjectType,
    ToolExecutionMode,
    ToolLifecycleStatus,
)


class ToolCategory(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """工具分类（`08-DDL基线.sql` / `04 §1`）。"""

    __tablename__ = "tool_category"

    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("tool_category.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="父分类 ID；NULL 表示根分类",
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="分类编码；唯一")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="分类名称")
    icon_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="图标 URL")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )

    __table_args__ = (
        Index(
            "uq_tool_category_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class Tool(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """工具（`08-DDL基线.sql` / `04 §2`）。"""

    __tablename__ = "tool"

    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tool_category.id", ondelete="RESTRICT"),
        nullable=False,
        comment="所属分类 ID",
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False, comment="工具编码；唯一")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="工具名称")
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True, comment="工具描述")
    component_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="组件键；映射到受控实现（见 §4）"
    )
    execution_mode: Mapped[ToolExecutionMode] = mapped_column(
        enum_type(ToolExecutionMode, name="execution_mode"),
        nullable=False,
        comment="执行模式 FRONTEND / BACKEND / ASYNC",
    )
    lifecycle_status: Mapped[ToolLifecycleStatus] = mapped_column(
        enum_type(ToolLifecycleStatus, name="lifecycle_status"),
        nullable=False,
        default=ToolLifecycleStatus.DRAFT,
        comment="生命周期 DRAFT / TESTING / ACTIVE / DISABLED",
    )
    visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PUBLIC", comment="可见性；取值域待冻结"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序")
    is_recommended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否推荐"
    )
    tags: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="标签集合")

    __table_args__ = (
        Index(
            "uq_tool_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class ToolVersion(PrimaryKeyMixin, Base):
    """工具版本（`08-DDL基线.sql` / `04 §3`：记录版本 / 配置版本 / 发布版本）。

    只有 created_at、无 updated_at（版本不可变）。
    """

    __tablename__ = "tool_version"

    tool_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tool.id", ondelete="RESTRICT"),
        nullable=False,
        comment="所属工具 ID",
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False, comment="版本号")
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="版本配置")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="DRAFT", comment="版本状态；取值域待冻结"
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="发布时间 (UTC)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )

    __table_args__ = (UniqueConstraint("tool_id", "version", name="uq_tool_version_tool"),)


class ToolComponentRegistry(PrimaryKeyMixin, TimestampMixin, Base):
    """组件注册（`08-DDL基线.sql` / `04 §4`）。

    `component_key` → 受控实现，禁止管理员填写任意 Vue import path。
    """

    __tablename__ = "tool_component_registry"

    component_key: Mapped[str] = mapped_column(String(128), nullable=False, comment="组件键；唯一")
    component_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="组件类型；取值域待冻结"
    )
    implementation_ref: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="受控实现引用"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )

    __table_args__ = (UniqueConstraint("component_key", name="uq_tool_component_registry_key"),)


class ToolAccessPolicy(PrimaryKeyMixin, TimestampMixin, Base):
    """工具访问策略（`08-DDL基线.sql` / `04 §5`）。

    USER_LEVEL 主体必须同时带 user_level_id；不设置 ADMIN 工具用户身份。
    """

    __tablename__ = "tool_access_policy"

    tool_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tool.id", ondelete="RESTRICT"),
        nullable=False,
        comment="所属工具 ID",
    )
    subject_type: Mapped[ToolAccessSubjectType] = mapped_column(
        enum_type(ToolAccessSubjectType, name="subject_type"),
        nullable=False,
        comment="主体类型 GUEST / USER_LEVEL",
    )
    user_level_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_user_level.id", ondelete="RESTRICT"),
        nullable=True,
        comment="USER_LEVEL 主体对应的等级 ID",
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")
    quota_config: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="额度配置"
    )


class ToolUsageEvent(PrimaryKeyMixin, Base):
    """工具使用事件（`08-DDL基线.sql` / `04 §6`）。

    记录每次使用的结果 / 耗时 / 执行模式 / trace_id；**禁止**写入口令、token、
    secret、完整代码、SQL、工具输入内容与文件内容（见 `04 §6`）。
    只有 created_at、无 updated_at。
    """

    __tablename__ = "tool_usage_event"

    tool_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="工具 ID")
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        nullable=True,
        comment="业务用户 ID；游客为 NULL",
    )
    anonymous_id_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="游客匿名 ID 哈希"
    )
    result: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="执行结果；取值域待冻结"
    )
    duration_ms: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="耗时（毫秒）"
    )
    execution_mode: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="执行模式；取值域待冻结"
    )
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="链路追踪 ID")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )

    __table_args__ = (Index("idx_tool_usage_tool_time", "tool_id", "created_at"),)


class ToolUsageDaily(PrimaryKeyMixin, Base):
    """工具日统计（`08-DDL基线.sql` / `04 §7`）。

    按工具 / 日期聚合；只有 created_at（写入即定稿），无 updated_at。
    """

    __tablename__ = "tool_usage_daily"

    tool_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="工具 ID")
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, comment="统计日期")
    total_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="总次数"
    )
    success_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="成功次数"
    )
    failure_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="失败次数"
    )
    guest_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="游客次数"
    )
    user_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="登录用户次数"
    )
    unique_user_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="独立用户数"
    )
    avg_duration_ms: Mapped[float | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="平均耗时（毫秒）"
    )

    __table_args__ = (
        UniqueConstraint("tool_id", "stat_date", name="uq_tool_usage_daily_tool_date"),
    )


class ToolRecentUsage(PrimaryKeyMixin, Base):
    """用户最近使用工具（`08-DDL基线.sql` / `04 §8`）。"""

    __tablename__ = "tool_recent_usage"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        nullable=False,
        comment="业务用户 ID",
    )
    tool_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tool.id", ondelete="RESTRICT"),
        nullable=False,
        comment="工具 ID",
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="最近使用时间 (UTC)"
    )
    use_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="使用次数"
    )

    __table_args__ = (UniqueConstraint("user_id", "tool_id", name="uq_tool_recent_usage_user"),)


class ToolPopularityDaily(PrimaryKeyMixin, Base):
    """工具热门统计（`08-DDL基线.sql` / `04 §9`：用于热门排序计算）。"""

    __tablename__ = "tool_popularity_daily"

    tool_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="工具 ID")
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, comment="统计日期")
    score: Mapped[float] = mapped_column(
        Numeric(20, 6), nullable=False, default=0, comment="热门得分"
    )
    rank_no: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="当日排名")

    __table_args__ = (
        UniqueConstraint("tool_id", "stat_date", name="uq_tool_popularity_daily_tool_date"),
    )


__all__ = [
    "Tool",
    "ToolAccessPolicy",
    "ToolCategory",
    "ToolComponentRegistry",
    "ToolPopularityDaily",
    "ToolRecentUsage",
    "ToolUsageDaily",
    "ToolUsageEvent",
    "ToolVersion",
]
