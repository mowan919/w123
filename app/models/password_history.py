"""密码历史模型。

Frozen 依据
-----------
Spec `00 §2`（= `15 D-009`）冻结的密码策略包含：
    「最近 5 个密码不可重复」

该策略要求保存历史密码哈希，但 Spec `07` 的建表清单中没有对应表
（07 §4/§5/§6/§7/§8 均未列出）。经人类裁定：**新建密码历史表**。

设计说明
-------
- 只保存**哈希**，绝不保存明文（`10 §4`）；
- 不设 `deleted_at`：历史记录是追加型审计数据，不参与软删除语义；
- `(user_id, created_at)` 联合索引用于"取最近 5 条"的校验查询；
- 保留条数的裁剪由 `UserService` 负责，DB 不做约束（避免隐式业务规则）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, utc_now


class AdminUserPasswordHistory(PrimaryKeyMixin, Base):
    """用户历史密码哈希（追加型）。"""

    __tablename__ = "admin_user_password_histories"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="用户 ID",
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="历史密码的 argon2id 哈希；绝不保存明文",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="写入时间 (UTC)",
    )

    __table_args__ = (
        Index(
            "ix_admin_user_password_histories_user_id_created_at",
            "user_id",
            "created_at",
        ),
    )


__all__ = ["AdminUserPasswordHistory"]
