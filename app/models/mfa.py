"""MFA 凭据、策略与挑战模型（DD-24 方案 A）。

Spec 依据与**为何是三张表**
---------------------------
- Spec `04 §6`：Provider 必须抽象；生命周期 `DISABLED → SETUP → ENABLED`；
  Secret 必须加密保存。
- Spec `04 §7`（= `00 §1#10` / `15 D-010`）：策略分 system / role / user 三层，
  优先级 `user > role > system`。
- Spec `07 §7`：**建议** `user_mfa` 包含 provider / status / encrypted_secret /
  setup_at / enabled_at / verified_at，且明写"具体字段随 Provider 设计确定"。

关键观察：`07 §7` 列出的字段**全部是凭据字段**，没有一处能表达 `04 §7` 要求的
"是否要求 MFA"。因此本实现把二者**拆成两张表**：

```text
mfa_policies    策略（"要不要"）—— 按主体存，subject_type ∈ {USER, ROLE}
user_mfa        凭据（"是什么"）—— 按用户 + Provider 存
mfa_challenges  挑战（DD-23）  —— 短期、一次性
```

为什么不把 `required` 并进 `user_mfa`：角色级策略**不属于任何用户**，
在 `user_mfa` 里无处安放；强行合并只能放弃角色级策略（违反 `04 §7`）。

本表**不含任何具体 Provider 的算法实现**
-----------------------------------------
`00 §4` / `16 §技术设计待冻结项#1` / `PHASES.md Phase 5` 一致禁止 Agent
把具体 Provider 宣布为需求事实。因此这里只有"Provider 的名字"与"它的密文"，
没有任何 TOTP / WebAuthn / SMS 相关字段或逻辑。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, TimestampMixin
from app.models.enums import MfaPolicySubject, MfaStatus

#:  Provider 名称列宽。与 `MFA_PROVIDER_NAME_MAX_LENGTH` 保持一致，
#:  该常量同时被 `MfaProviderRegistry.register` 用于在注册时拒绝超长名字。
PROVIDER_NAME_LENGTH = 32


class UserMfa(PrimaryKeyMixin, TimestampMixin, Base):
    """用户 MFA 凭据（每个 `user_id` + `provider` 至多一条）。

    唯一键为什么包含 `provider`
    --------------------------
    支持同一用户将来**迁移** Provider 时新旧凭据**并存**：
    例如从 TOTP 迁到 WebAuthn 的过程中，两行同时存在，
    由 `MfaProviderRegistry.active_name` 决定此刻用哪一个校验
    （`MfaProvider.name` 的语义就是为此保留的）。

    若唯一键只有 `user_id`，迁移就会变成"删旧的、建新的" ——
    一旦新凭据配置失败，用户已经失去了旧的，直接被锁在门外；
    并存使得"回退"始终是一个可选动作。

    为什么不设 `deleted_at`
    ----------------------
    凭据的终态由 `status = DISABLED` 表达（生命周期的起点也是终点）。
    再引入软删除会出现"`status` 与 `deleted_at` 谁说了算"的第二套语义。
    用户被逻辑删除后，本行仍保留（不物理删除是对取证友好的默认）。
    """

    __tablename__ = "user_mfa"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="用户 ID",
    )
    provider: Mapped[str] = mapped_column(
        String(PROVIDER_NAME_LENGTH),
        nullable=False,
        comment="MFA Provider 名称（对应 MfaProvider.name）",
    )
    status: Mapped[MfaStatus] = mapped_column(
        nullable=False,
        default=MfaStatus.DISABLED,
        comment="生命周期状态 DISABLED / SETUP / ENABLED（Spec 04 §6 冻结的三态）",
    )
    encrypted_secret: Mapped[str | None] = mapped_column(
        # AEAD 密文 base64 后的长度随明文长度变化，用定长列会埋下**静默截断**风险：
        # 截断后解密必然失败，且排查时看不出来是列宽问题。故用不限长 Text（DD-22 P1）。
        Text,
        nullable=True,
        comment="AES-256-GCM 密文 `v1.<base64url(nonce ‖ ct ‖ tag)>`；AAD 绑定 user_id + provider",
    )
    setup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="进入 SETUP 的时间 (UTC)"
    )
    enabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="启用时间 (UTC)"
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近一次校验成功的时间 (UTC)"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_mfa_user_provider"),
        Index("ix_user_mfa_user_id", "user_id"),
    )


class MfaPolicy(PrimaryKeyMixin, TimestampMixin, Base):
    """MFA 策略（是否要求二次验证），作用于 USER 或 ROLE 两种主体。

    `required` 为什么必须**可空**
    -----------------------------
    - `NULL`   = **未表态**：这一层没有意见，解析器继续向下一层询问；
    - `False`  = **明确不要求**：解析器**终止**，不再向下询问。

    这两者合并的后果是永久性的：一旦某一层存在实现，
    返回 `False` 就会**永久屏蔽**其下所有层级的策略，
    且运行时完全看不出来（策略静默失效）。
    该语义在 Phase 4 已由 `UnsetUserMfaPolicySource` / `UnsetRoleMfaPolicySource`
    固化（它们返回 `None` 而非 `False`），本表必须与之一致。

    为什么不用两个可空外键（`user_id` / `role_id`）
    ---------------------------------------------
    "两列必有一列 NULL"的模式约束难写、索引利用率低，
    且无法用一个唯一约束表达"每主体至多一条策略"。
    代价是 `subject_id` 上没有数据库外键 —— 引用完整性由服务层校验
    （登记为 INTERIM：这不是"省略校验"，而是把校验放在知道主体类型的地方）。
    """

    __tablename__ = "mfa_policies"

    subject_type: Mapped[MfaPolicySubject] = mapped_column(
        nullable=False, comment="策略主体类型 USER / ROLE"
    )
    subject_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="主体 ID（Snowflake）：用户 ID 或角色 ID"
    )
    required: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        comment="是否要求 MFA；NULL = 该层未表态（与 False 语义不同，见类文档）",
    )

    __table_args__ = (
        UniqueConstraint("subject_type", "subject_id", name="uq_mfa_policies_subject"),
        Index("ix_mfa_policies_subject", "subject_type", "subject_id"),
    )


class MfaChallenge(PrimaryKeyMixin, TimestampMixin, Base):
    """登录过程中的一次性 MFA 挑战（DD-23 方案 A）。

    存在的前提
    ----------
    Spec `04 §1` 的顺序图把 `create session` 放在 `MFA check` **之后**，
    而 `08 §3` 又要求存在 `POST /auth/mfa/verify`。
    因此"口令已通过、二次验证未完成"这一中间态必须有载体 —— 就是本表。

    为什么不是"提前建 Session 并标记 pending"
    ----------------------------------------
    Phase 4 已验收的在线判定是「未撤销 + 未过期 + 用户 ACTIVE」，
    提前建行会让**只输对密码的人**立刻显示为在线；
    更严重的是：认证是否完成会退化成 `sessions` 上的一个**可选列**，
    任何一条漏检该列的鉴权路径都是认证绕过。
    把安全状态放在"默认放行"的位置是不可接受的。

    挑战令牌本身只库存哈希
    ---------------------
    与 access / refresh 同口径（`app/core/security/token.py::hash_token`）：
    库中只有 SHA-256，令牌原文仅存在于客户端。
    一旦 DB 泄漏，攻击者无法用哈希去续完任何一次登录。
    """

    __tablename__ = "mfa_challenges"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
        comment="用户 ID",
    )
    provider: Mapped[str] = mapped_column(
        String(PROVIDER_NAME_LENGTH), nullable=False, comment="本次挑战使用的 Provider 名称"
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="挑战令牌的 SHA-256 哈希；库内绝不保存明文（与 access/refresh 同口径）",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="过期时间 (UTC)"
    )
    attempts: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        comment="已失败次数；达到上限即失效（DD-23 Q4，不锁账号）",
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="核销时间 (UTC)：成功或被判定作废后写入"
    )

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_mfa_challenges_token_hash"),
        Index("ix_mfa_challenges_user_id", "user_id"),
    )


__all__ = ["PROVIDER_NAME_LENGTH", "MfaChallenge", "MfaPolicy", "UserMfa"]
