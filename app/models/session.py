"""会话（Session）与已退役 Refresh Token 的持久化模型。

Frozen 依据
-----------
Spec `07 §6`（sessions 表必须至少包含）：
    id / user_id / token identifier | hash / login_at / last_active_at /
    ip / user_agent / device / expires_at / revoked_at / revoke_reason

Spec `04 §3`：
    必须记录 session id / user id / login time / last active / IP /
    user agent / device / expires_at / revoked_at / revoke_reason /
    token identifiers；
    **Refresh Token 必须哈希存储，不得保存明文。**

Spec `10 §7`：
    Revoke 后 Token 必须不能继续访问；Revoke all 后所有对应 Session 都必须失效。

已裁定的技术决策（DD-02 **方案 A**，DD-03 **方案 A**）
---------------------------------------------------
- 令牌为**不透明随机串**，PG 中的 `sessions` 是**唯一真源**；
- **不引入 Redis**（DD-03 留到 Phase 9 只读缓存），因此不存在"两个真相"；
- 每请求按 `access_token_hash` 查本表并校验未过期、未撤销 ——
  这正是 `10 §7` 得以成立的机制（无需 denylist）。

为什么 `sessions` 没有 `deleted_at`
---------------------------------
会话不是"可删除的业务实体"，它的终态是**被撤销**（`revoked_at`）而不是"被删除"。
若引入软删除，就会出现"`revoked_at` 与 `deleted_at` 谁说了算"的第二套语义，
而 Spec `04 §3` 已经把撤销定义为带原因的状态迁移。
因此本表不参与软删除语义；数据留存 / 归档 / 分区属 Phase 6（DD-08）。

为什么需要 `session_refresh_token_history`
---------------------------------------
DD-02 P4 冻结："已轮换的 Refresh Token 再次被使用 → 撤销该 session 的全部令牌"。
要判断"这个 Refresh Token 曾被轮换过"，就必须**记得**已经被轮换掉的哈希 ——
否则旧令牌只会表现为"查不到"，从而**无法区分**
"攻击者在重放旧令牌"与"客户端拼错了一个随机串"。
因此把退役的 Refresh Token 哈希单独留档：

```text
当前有效的 refresh 哈希 → sessions.refresh_token_hash        （唯一真源，只有一条）
已退役的 refresh 哈希   → session_refresh_token_history       （判定盗用信号）
```

两者**互斥**：任一枚举值在任一时刻只存在于其中一处，不存在重复真相。

**只记录 Refresh Token，不记录 Access Token**：Access 的 TTL 仅 15 分钟，
且"重放一个已轮换的 access token"没有任何攻击价值 ——
它只会查不到而被拒（401）。若把每 15 分钟轮换的 access 也留档，
一个 7 天会话就会产生约 672 行纯噪声记录。这是刻意的取舍，不是遗漏。
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security.token import TOKEN_HASH_LENGTH
from app.db.base import Base, PrimaryKeyMixin, TimestampMixin, utc_now
from app.db.types import enum_type
from app.models.enums import RefreshTokenRetirement, SessionRevokeReason


class UserSession(PrimaryKeyMixin, TimestampMixin, Base):
    """一次登录产生的会话（PG 为唯一真源）。

    字段与 Spec `07 §6` 的对应关系：

    | Spec 字段 | 本表列 |
    |---|---|
    | session id | `id`（Snowflake BIGINT） |
    | user id | `user_id` |
    | token identifier/hash | `access_token_hash` / `refresh_token_hash`（SHA-256） |
    | login time | `login_at` |
    | last active | `last_active_at` |
    | ip / user agent / device | `ip` / `user_agent` / `device` |
    | expires_at | `expires_at`（access）＋ `refresh_expires_at`（refresh） |
    | revoked_at / revoke_reason | `revoked_at` / `revoke_reason` |

    `refresh_expires_at` 是本实现**必须**新增的列：`04` 定义了两种令牌，
    它们的寿命相差 672 倍（15 分钟 vs 7 天），
    用一个 `expires_at` 无法同时表达"access 已过期但 refresh 仍可换取新 access"
    —— 而那正是"刷新"存在的意义。这不是对 Spec 的扩展，
    而是把 Spec `07 §6` 的 `expires_at` 落到"两个令牌各有其到期时间"。
    """

    __tablename__ = "sessions"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="会话所属用户 ID",
    )
    access_token_hash: Mapped[str] = mapped_column(
        String(TOKEN_HASH_LENGTH),
        nullable=False,
        comment="当前 Access Token 的 SHA-256；绝不保存明文（Spec 10 §4）",
    )
    refresh_token_hash: Mapped[str] = mapped_column(
        String(TOKEN_HASH_LENGTH),
        nullable=False,
        comment="当前 Refresh Token 的 SHA-256；绝不保存明文（Spec 04 §3）",
    )
    login_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="登录时间 (UTC)",
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="最近活动时间 (UTC)；写放大受 SESSION_ACTIVITY_WRITE_INTERVAL 抑制",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="当前 Access Token 过期时间 (UTC)；轮换时前移，不延长会话总寿命",
    )
    refresh_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Refresh Token 过期时间 (UTC)；登录时确定，轮换**不**延长（DD-02 P2 固定）",
    )
    ip: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="登录来源 IP；可空（代理/内网场景可能取不到）",
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="原始 User-Agent，仅用于展示与取证",
    )
    device: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="设备粗分类（启发式，**非安全依据**；见 app.core.security.device）",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="撤销时间 (UTC)；NULL 表示仍有效。改此列即**立即**生效（Spec 10 §7）",
    )
    revoke_reason: Mapped[SessionRevokeReason | None] = mapped_column(
        enum_type(SessionRevokeReason, name="revoke_reason", length=32),
        nullable=True,
        comment="撤销原因；与 revoked_at 同生共死（CHECK 保证）",
    )

    __table_args__ = (
        # 按令牌反查会话是**每个请求**的热路径，必须是唯一索引：
        # 唯一性同时保证"一个令牌不可能对应两个会话"这一安全前提。
        Index("uq_sessions_access_token_hash", "access_token_hash", unique=True),
        Index("uq_sessions_refresh_token_hash", "refresh_token_hash", unique=True),
        # 撤销语义的完整性：不能出现"已撤销但无原因"或"未撤销却有原因"。
        # 这两种中间态会让审计无法回答"这个会话为什么结束"。
        CheckConstraint(
            "(revoked_at IS NULL) = (revoke_reason IS NULL)",
            name="revocation_fields_consistent",
        ),
        # 时间计算的完整性探针。
        #
        # `expires_at > login_at`：登录时签发的 access 不可能在登录时刻就已过期。
        # 轮换只把 `expires_at` 往前推，因此该式恒成立。
        #
        # `refresh_expires_at >= expires_at`：**不**是一条业务规则，
        # 而是一条"TTL 用反了"的探针 —— 它由
        # `SessionService.rotated_access_expiry` 在轮换时构造性保证
        # （新 access 的到期时间被会话总寿命封顶）。
        # 之所以保留它而不是删掉：若有人把 ACCESS/REFRESH 的常量对调，
        # 唯一会立刻炸出来的地方就是这里（否则表现为"登录过一段时间后
        # 所有会话莫名失效"，排查成本高得多）。
        CheckConstraint("expires_at > login_at", name="access_expires_after_login"),
        CheckConstraint(
            "refresh_expires_at >= expires_at",
            name="refresh_expires_not_before_access",
        ),
    )

    @property
    def is_revoked(self) -> bool:
        """是否已被撤销。"""
        return self.revoked_at is not None

    def is_access_expired(self, now: datetime) -> bool:
        """Access Token 是否已过期。"""
        return now >= self.expires_at

    def is_refresh_expired(self, now: datetime) -> bool:
        """Refresh Token 是否已过期（会话总寿命上界）。"""
        return now >= self.refresh_expires_at

    def is_active(self, now: datetime) -> bool:
        """会话是否仍然有效（未撤销且 refresh 未过期）。

        注意：**不**检查 access 是否过期 —— "access 过期但 refresh 有效"
        正是需要刷新令牌的正常状态。判断 access 请用 `is_access_expired`。
        """
        return not self.is_revoked and not self.is_refresh_expired(now)


class SessionRefreshTokenHistory(PrimaryKeyMixin, Base):
    """已退役 Refresh Token 的留档（用于盗用检测与取证）。

    写入时机只有两处：

    1. **轮换**：旧 refresh 被新 refresh 取代 → `reason = ROTATED`；
    2. **撤销**：会话被撤销时，把当时的 refresh 一并留档
       → `reason = SESSION_REVOKED`。

    查询时机：`POST /auth/refresh` 收到一个**不在** `sessions.refresh_token_hash`
    里的令牌时，来这里判定它是否"曾经合法过"。只有 `ROTATED` 才算盗用信号。

    表按**追加**语义使用（`retired_at` 只写一次），不含 `deleted_at`。
    """

    __tablename__ = "session_refresh_token_history"

    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="该令牌所属会话 ID",
    )
    token_hash: Mapped[str] = mapped_column(
        String(TOKEN_HASH_LENGTH),
        nullable=False,
        comment="已退役 Refresh Token 的 SHA-256；绝不保存明文",
    )
    reason: Mapped[RefreshTokenRetirement] = mapped_column(
        enum_type(RefreshTokenRetirement, name="reason", length=32),
        nullable=False,
        comment="退役原因：ROTATED（盗用信号）/ SESSION_REVOKED（会话已撤销）",
    )
    retired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="退役时间 (UTC)",
    )

    __table_args__ = (
        Index("uq_session_refresh_token_history_token_hash", "token_hash", unique=True),
    )


__all__ = ["SessionRefreshTokenHistory", "UserSession"]
