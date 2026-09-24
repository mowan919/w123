"""SQLAlchemy 公共列类型。

设计说明（INTERIM 技术决策，非业务规则）
--------------------------------------
枚举列使用 `native_enum=False`，生成 `VARCHAR + CHECK`，
而不是 PostgreSQL 原生 ENUM 类型。

理由：
1. 原生 ENUM 增加取值需要 `ALTER TYPE`，且不能在事务内安全回滚，
   对 Spec `13 §3` "migration 必须可审查、可回滚" 不利；
2. VARCHAR + CHECK 的 migration 是纯 DDL diff，便于审查。

约束命名交给 `app.db.base.NAMING_CONVENTION` 的 `ck` 规则，
即最终名称为 `ck_<table>_<name>`。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import Enum as SAEnum


def enum_type(enum_cls: type[StrEnum], *, name: str = "status", length: int = 16) -> SAEnum:
    """构造 VARCHAR + CHECK 形式的枚举列类型。

    Args:
        enum_cls: `StrEnum` 子类。
        name: 约束名片段，最终由 naming_convention 拼成 `ck_<table>_<name>`。
        length: VARCHAR 长度，需大于最长枚举值。
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=length,
    )


__all__: list[Any] = ["enum_type"]
