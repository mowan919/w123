"""公共 Pydantic 类型。

Frozen（Spec 07 §2 / 00 §6 / AGENTS.md §6）：
    API JSON 中 BIGINT 业务 ID 统一序列化为字符串。

实现方式说明：
- 采用**显式类型标注**而非全局 int→str 编码。
  原因是全局转换会把 `total`、`count`、`page_size` 等计数类字段一并变成字符串，
  违反"仅业务 ID 序列化为字符串"的冻结语义。
- 所有业务 ID 字段必须使用 `SnowflakeId` 标注。
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer

MAX_BIGINT = (1 << 63) - 1


def _parse_snowflake(value: Any) -> int:
    """接受字符串或整数输入，校验为合法 BIGINT，统一返回 int。

    合并为单个 before-validator，避免多个 BeforeValidator 执行顺序
    导致"先比较范围、后做类型转换"的错误。
    """
    # bool 是 int 的子类，但语义上不是合法 ID，显式拒绝
    if isinstance(value, bool):
        raise ValueError("Snowflake ID 不能为布尔值")

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped.isdigit():
            raise ValueError("Snowflake ID 必须为数字字符串")
        value = int(stripped)

    if not isinstance(value, int):
        raise ValueError(f"Snowflake ID 必须为整数或数字字符串，实际为 {type(value).__name__}")

    if value < 0 or value > MAX_BIGINT:
        raise ValueError(f"Snowflake ID 超出 BIGINT 范围: {value}")

    return value


SnowflakeId = Annotated[
    int,
    BeforeValidator(_parse_snowflake),
    # 仅 JSON 输出时转字符串：Python 内部仍为 int，避免影响业务计算
    PlainSerializer(str, return_type=str, when_used="json"),
]
"""BIGINT + Snowflake 业务 ID 类型。

- 输入：`"123456789"` 或 `123456789`
- Python 值：`int`
- JSON 输出：`"123456789"`
"""
