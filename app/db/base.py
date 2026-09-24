"""SQLAlchemy 声明式基类与公共列。

Spec 07 §3 Common Columns：
    核心业务表：id / created_at / updated_at
    可删除业务表：deleted_at

Spec 07 §9 Constraints 要求命名可控，便于 Alembic 生成稳定、可审查的 migration。
因此这里统一设置 naming_convention（Spec 13 §3 "Migration 必须可审查"）。

本阶段**不定义任何业务表**（PHASE-001 明确禁止 User / Role / Permission 等业务模型）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.core.snowflake import next_id

#: 约束命名规范。Spec 07 §9：必须检查 FK / index / unique / soft-delete-aware unique
#: / parent-child index / user/role indexes / session lookup indexes / audit trace indexes
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    """返回带时区的当前 UTC 时间。

    Spec 00 §6：时间统一 UTC。
    """
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __repr__(self) -> str:
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


class PrimaryKeyMixin:
    """BIGINT + Snowflake 主键。

    Frozen（Spec 00 §6 / 07 §2）：业务主键必须为 BIGINT + Snowflake，
    禁止自增、禁止 UUID。生成逻辑见 `app.core.snowflake`。

    注意：这里显式指定 `BigInteger` 且 `autoincrement=False`，
    以杜绝"顺手用自增 ID"的实现偏差。

    `default=next_id` 是 **Python 侧默认值**（不产生任何 DDL），
    单实例下无需手工赋值即可 flush；Seed 或需要外部指定 ID 的场景
    仍可显式传入（Spec 07 §10）。
    """

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
        default=next_id,
        comment="Snowflake BIGINT 业务主键",
    )


class TimestampMixin:
    """created_at / updated_at（UTC）。"""

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            default=utc_now,
            server_default=None,
            comment="创建时间 (UTC)",
        )

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            default=utc_now,
            onupdate=utc_now,
            comment="更新时间 (UTC)",
        )


class SoftDeleteMixin:
    """deleted_at 逻辑删除。

    Frozen（Spec 00 §6 / 02 §5 / 07 §3）：
    默认逻辑删除；查询必须考虑 soft delete；
    唯一约束必须考虑逻辑删除后的重建问题
    （PostgreSQL 需使用 partial unique index，由具体业务表实现）。
    """

    @declared_attr
    def deleted_at(cls) -> Mapped[datetime | None]:
        return mapped_column(
            DateTime(timezone=True),
            nullable=True,
            default=None,
            index=True,
            comment="逻辑删除时间 (UTC)，NULL 表示未删除",
        )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
