"""用户成长中心模型 —— V3.1 数据库设计基线（`03 用户成长中心` + `08-DDL基线.sql`）。

Frozen 依据
-----------
- `08-DDL基线.sql` 的 Growth 段落是结构基线，本文件严格按基线落库。
- `03 §14 / §15` 的 任务 / 成就 四张表 DDL 基线**未包含**（仅文字描述），
  其结构属 INTERIM 技术推导，保持最小可审查，等待冻结决策（§33）。
- 成长值与积分**分离**（`03` 原则 #9），流水**不可更新、不可删除**（`03 §6`）：
  流水表只有 created_at、无 updated_at、无逻辑删除。

状态 / 类型列说明
----------------
rule / level / benefit / cosmetic 等的通用 status 列 DDL 仅给 DEFAULT 'ACTIVE'、
未枚举取值域，以普通 VARCHAR 落库（不发明取值）。仅 `cosmetic_type`
（`03 §11` 显式枚举六种）以枚举列落库。source_type / event_type /
benefit_type / change_type / task_type / repeat_type 等均不枚举，以 String 落库，
取值域待冻结。

⚠️ 本文件只落**结构**。规则引擎、幂等、等级计算、周期限制等业务语义
（`03 §16`）属未冻结项（见 `09-数据库完整性检查.md` C 段），不在本文件实现。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin, utc_now
from app.db.types import enum_type
from app.models.enums import CosmeticType


class BizUserGrowthAccount(PrimaryKeyMixin, TimestampMixin, Base):
    """用户成长账户（`08-DDL基线.sql` / `03 §1`）。

    user_id 唯一（一人一户）。current_level_id 冗余当前等级，便于读取。
    """

    __tablename__ = "biz_user_growth_account"

    user_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, comment="业务用户 ID（唯一）"
    )
    total_growth_points: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="累计成长值"
    )
    current_level_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_user_level.id", ondelete="RESTRICT"),
        nullable=True,
        comment="当前等级 ID",
    )


class BizUserPointAccount(PrimaryKeyMixin, TimestampMixin, Base):
    """用户积分账户（`08-DDL基线.sql` / `03 §2`）。

    balance_points = total_earned - total_spent，三个非负约束由库层 CHECK 强制。
    """

    __tablename__ = "biz_user_point_account"

    user_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, comment="业务用户 ID（唯一）"
    )
    total_earned_points: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="累计获得积分"
    )
    total_spent_points: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="累计消费积分"
    )
    balance_points: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="可用余额积分"
    )

    __table_args__ = (
        CheckConstraint("total_earned_points >= 0", name="earned_non_negative"),
        CheckConstraint("total_spent_points >= 0", name="spent_non_negative"),
        CheckConstraint("balance_points >= 0", name="balance_non_negative"),
    )


class BizGrowthRule(PrimaryKeyMixin, TimestampMixin, Base):
    """成长规则（`08-DDL基线.sql` / `03 §3`）。

    source_type / event_type 等取值域待冻结；本表只落结构。
    """

    __tablename__ = "biz_growth_rule"

    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="规则编码；唯一")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="规则名称")
    source_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="来源类型；取值域待冻结"
    )
    event_type: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="事件类型；取值域待冻结"
    )
    reward_points: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="奖励成长值")
    daily_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="每日上限（次）"
    )
    weekly_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="每周上限（次）"
    )
    monthly_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="每月上限（次）"
    )
    cooldown_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="冷却秒数")
    requires_success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否要求业务成功才奖励"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="生效开始 (UTC)"
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="生效结束 (UTC)"
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="规则描述")

    __table_args__ = (UniqueConstraint("code", name="uq_biz_growth_rule_code"),)


class BizPointRule(PrimaryKeyMixin, TimestampMixin, Base):
    """积分规则（`08-DDL基线.sql` / `03 §4`：结构与成长规则一致）。"""

    __tablename__ = "biz_point_rule"

    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="规则编码；唯一")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="规则名称")
    source_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="来源类型；取值域待冻结"
    )
    event_type: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="事件类型；取值域待冻结"
    )
    reward_points: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="奖励积分")
    daily_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="每日上限（次）"
    )
    weekly_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="每周上限（次）"
    )
    monthly_limit: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="每月上限（次）"
    )
    cooldown_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="冷却秒数")
    requires_success: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否要求业务成功才奖励"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="生效开始 (UTC)"
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="生效结束 (UTC)"
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="规则描述")

    __table_args__ = (UniqueConstraint("code", name="uq_biz_point_rule_code"),)


class BizGrowthEvent(PrimaryKeyMixin, Base):
    """业务成长事件（`08-DDL基线.sql` / `03 §5`）。

    事件驱动奖励的入口；event_id 与 idempotency_key 双唯一保证幂等。
    只有 created_at、无 updated_at（事件不可变）。
    """

    __tablename__ = "biz_growth_event"

    event_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="业务事件 ID；唯一")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="业务用户 ID")
    source_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="来源类型；取值域待冻结"
    )
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="来源 ID")
    event_type: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="事件类型；取值域待冻结"
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="幂等键；唯一"
    )
    event_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="事件载荷（禁止写入敏感业务内容）"
    )
    processed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否已处理"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="处理时间 (UTC)"
    )

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_biz_growth_event_id"),
        UniqueConstraint("idempotency_key", name="uq_biz_growth_event_idempotency"),
        Index("ix_biz_growth_event_user_time", "user_id", "created_at"),
        Index("ix_biz_growth_event_type_time", "event_type", "created_at"),
    )


class BizUserGrowthTransaction(PrimaryKeyMixin, Base):
    """成长流水（`08-DDL基线.sql` / `03 §6`）。

    流水只能 INSERT，业务 API 禁止 UPDATE / DELETE（见 `03 §6`）。
    只有 created_at、无 updated_at。
    """

    __tablename__ = "biz_user_growth_transaction"

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="业务用户 ID")
    change_points: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="变动成长值（负为扣减）"
    )
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="变动后余额")
    rule_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_growth_rule.id", ondelete="RESTRICT"),
        nullable=True,
        comment="关联规则 ID",
    )
    source_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="来源类型；取值域待冻结"
    )
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="来源 ID")
    event_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="关联事件 ID")
    transaction_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="流水类型；取值域待冻结"
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="描述")
    operator_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="操作主体类型；取值域待冻结"
    )
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="操作主体 ID"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )

    __table_args__ = (Index("idx_biz_growth_tx_user_time", "user_id", text("created_at DESC")),)


class BizUserPointTransaction(PrimaryKeyMixin, Base):
    """积分流水（`08-DDL基线.sql` / `03 §7`：结构与成长流水一致）。"""

    __tablename__ = "biz_user_point_transaction"

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="业务用户 ID")
    change_points: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="变动积分（负为扣减）"
    )
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="变动后余额")
    rule_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_point_rule.id", ondelete="RESTRICT"),
        nullable=True,
        comment="关联规则 ID",
    )
    source_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="来源类型；取值域待冻结"
    )
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="来源 ID")
    event_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="关联事件 ID")
    transaction_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="流水类型；取值域待冻结"
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="描述")
    operator_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="操作主体类型；取值域待冻结"
    )
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="操作主体 ID"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )

    __table_args__ = (Index("idx_biz_point_tx_user_time", "user_id", text("created_at DESC")),)


class BizUserLevelHistory(PrimaryKeyMixin, Base):
    """用户等级历史（`08-DDL基线.sql` / `03 §9`）。

    只有 created_at、无 updated_at（历史不可变）。
    """

    __tablename__ = "biz_user_level_history"

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="业务用户 ID")
    from_level_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_user_level.id", ondelete="RESTRICT"),
        nullable=True,
        comment="原等级 ID",
    )
    to_level_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user_level.id", ondelete="RESTRICT"),
        nullable=False,
        comment="目标等级 ID",
    )
    growth_points: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="当时成长值")
    change_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="变动类型；取值域待冻结"
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="变动原因")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )


class BizUserLevelBenefit(PrimaryKeyMixin, TimestampMixin, Base):
    """等级权益（`08-DDL基线.sql` / `03 §10`）。"""

    __tablename__ = "biz_user_level_benefit"

    level_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user_level.id", ondelete="RESTRICT"),
        nullable=False,
        comment="等级 ID",
    )
    benefit_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="权益类型；取值域待冻结"
    )
    benefit_code: Mapped[str] = mapped_column(String(128), nullable=False, comment="权益编码")
    benefit_value: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="权益配置"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )

    __table_args__ = (Index("ix_biz_user_level_benefit_level", "level_id"),)


class BizCosmetic(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """装扮定义（`08-DDL基线.sql` / `03 §11`）。"""

    __tablename__ = "biz_cosmetic"

    code: Mapped[str] = mapped_column(String(128), nullable=False, comment="装扮编码；唯一")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="装扮名称")
    cosmetic_type: Mapped[CosmeticType] = mapped_column(
        enum_type(CosmeticType, name="cosmetic_type"),
        nullable=False,
        comment="装扮类型 AVATAR/AVATAR_FRAME/CROWN/BADGE/TITLE/NAME_EFFECT",
    )
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="图片 URL")
    animation_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="动画 URL"
    )
    rarity: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="稀有度；取值域待冻结"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="描述")

    __table_args__ = (
        Index(
            "uq_biz_cosmetic_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class BizUserCosmetic(PrimaryKeyMixin, Base):
    """用户装扮资产（`08-DDL基线.sql` / `03 §12`）。

    只有 acquired_at、无 created_at / updated_at。
    """

    __tablename__ = "biz_user_cosmetic"

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="业务用户 ID")
    cosmetic_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_cosmetic.id", ondelete="RESTRICT"),
        nullable=False,
        comment="装扮 ID",
    )
    source_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="获取来源类型；取值域待冻结"
    )
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="获取来源 ID")
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="获取时间 (UTC)"
    )

    __table_args__ = (UniqueConstraint("user_id", "cosmetic_id", name="uq_user_cosmetic_owned"),)


class BizUserEquipment(PrimaryKeyMixin, Base):
    """用户当前装备（`08-DDL基线.sql` / `03 §13`）。

    只有 updated_at、无 created_at（装备记录随用户创建）。
    """

    __tablename__ = "biz_user_equipment"

    user_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, comment="业务用户 ID（唯一）"
    )
    avatar_cosmetic_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_cosmetic.id", ondelete="RESTRICT"),
        nullable=True,
        comment="头像装扮 ID",
    )
    avatar_frame_cosmetic_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_cosmetic.id", ondelete="RESTRICT"),
        nullable=True,
        comment="头像框装扮 ID",
    )
    crown_cosmetic_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_cosmetic.id", ondelete="RESTRICT"),
        nullable=True,
        comment="皇冠装扮 ID",
    )
    badge_cosmetic_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_cosmetic.id", ondelete="RESTRICT"),
        nullable=True,
        comment="徽章装扮 ID",
    )
    title_cosmetic_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_cosmetic.id", ondelete="RESTRICT"),
        nullable=True,
        comment="头衔装扮 ID",
    )
    name_effect_cosmetic_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_cosmetic.id", ondelete="RESTRICT"),
        nullable=True,
        comment="昵称特效装扮 ID",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        comment="更新时间 (UTC)",
    )


# ---------------------------------------------------------------------------
# 任务 / 成就四张表 DDL 基线未包含（`03 §14 / §15` 仅文字描述），属 INTERIM 推导，
# 等待冻结决策（见 DESIGN-DECISIONS §33）。
# ---------------------------------------------------------------------------


class BizTask(PrimaryKeyMixin, TimestampMixin, Base):
    """成长任务定义（`03 §14` 文字描述，DDL 基线未包含）。"""

    __tablename__ = "biz_task"

    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务编码；唯一")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="任务名称")
    task_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="任务类型；取值域待冻结"
    )
    target_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="目标值")
    reward_growth_points: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="奖励成长值"
    )
    reward_points: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="奖励积分"
    )
    repeat_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ONCE", comment="重复类型；取值域待冻结"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="生效开始 (UTC)"
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="生效结束 (UTC)"
    )

    __table_args__ = (UniqueConstraint("code", name="uq_biz_task_code"),)


class BizUserTask(PrimaryKeyMixin, Base):
    """用户任务进度（`03 §14` 文字描述，DDL 基线未包含）。

    只有 created_at（acquired/assigned），无 updated_at（进度字段直接覆盖更新）。
    """

    __tablename__ = "biz_user_task"

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="业务用户 ID")
    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_task.id", ondelete="RESTRICT"),
        nullable=False,
        comment="任务 ID",
    )
    progress: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="当前进度")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="IN_PROGRESS", comment="任务状态；取值域待冻结"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="完成时间 (UTC)"
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="领取奖励时间 (UTC)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )

    __table_args__ = (UniqueConstraint("user_id", "task_id", name="uq_biz_user_task_user"),)


class BizAchievement(PrimaryKeyMixin, TimestampMixin, Base):
    """成就定义（`03 §15` 文字描述，DDL 基线未包含）。"""

    __tablename__ = "biz_achievement"

    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="成就编码；唯一")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="成就名称")
    icon_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="图标 URL")
    achievement_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="成就类型；取值域待冻结"
    )
    target_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="目标值")
    reward_growth_points: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="奖励成长值"
    )
    reward_points: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="奖励积分"
    )
    reward_cosmetic_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_cosmetic.id", ondelete="RESTRICT"),
        nullable=True,
        comment="奖励装扮 ID",
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )

    __table_args__ = (UniqueConstraint("code", name="uq_biz_achievement_code"),)


class BizUserAchievement(PrimaryKeyMixin, Base):
    """用户成就进度（`03 §15` 文字描述，DDL 基线未包含）。"""

    __tablename__ = "biz_user_achievement"

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="业务用户 ID")
    achievement_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_achievement.id", ondelete="RESTRICT"),
        nullable=False,
        comment="成就 ID",
    )
    progress: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="当前进度")
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="完成时间 (UTC)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "achievement_id", name="uq_biz_user_achievement_user"),
    )


__all__ = [
    "BizAchievement",
    "BizCosmetic",
    "BizGrowthEvent",
    "BizGrowthRule",
    "BizPointRule",
    "BizTask",
    "BizUserAchievement",
    "BizUserCosmetic",
    "BizUserEquipment",
    "BizUserGrowthAccount",
    "BizUserGrowthTransaction",
    "BizUserLevelBenefit",
    "BizUserLevelHistory",
    "BizUserPointAccount",
    "BizUserPointTransaction",
    "BizUserTask",
]
