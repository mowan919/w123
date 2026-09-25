"""系统参数模型（Spec `05 §5`）。

Frozen 依据
-----------
Spec `05 §5`：

```text
System Parameter 与 Dictionary 分离。

参数示例：session timeout / login max attempts /
          password minimum length / MFA default policy

参数必须有类型、默认值、状态、描述和审计。
```

因此本表必须能表达：**类型**（`param_type`）、**默认值**
（`default_value`）、**状态**（`status`）、**描述**（`description`）。
"审计"由服务层对每次写入产生 `06 §2` 的审计事件满足（不是列）。

表名为什么是 `sys_params`（INTERIM-7-01）
-------------------------------------
Spec `05 §5` **未给出表名**，而同一份 Spec 的 §2 把字典表命名为
`sys_dict_type` / `sys_dict_item`。取 `sys_params` 是对该命名惯例的
最小推导：同一份文档、同一前缀、复数名词。已登记为 INTERIM 技术取值，
若人类冻结了另一个名字，改动面是"一次 migration + 一处 `__tablename__`"。

值与默认值为什么都是文本列
------------------------
`param_type` 表达**语义类型**（STRING / INT / BOOL），
`param_value` / `default_value` 以文本承载**字面量**，由服务层按类型解析。
这样做而不是分列（`int_value` / `bool_value` / …）：

1. 分列会让"哪一列有效"依赖于 `param_type`，形成第二真相 ——
   写入方漏写一列不会有任何报错，读取方却拿到 `NULL`；
2. 类型集合未冻结（`05 §5` 只列示例），增加一个类型就要加一列并迁移；
3. 文本 + 严格解析把"类型不匹配"变成**一次显式失败**（fail-closed），
   而不是一个默认值以外的、类型正确的空值。

代价明确记录：数据库层不再保证"INT 参数的值一定是整数"，
该校验落在服务层（`SystemParameterService`）；直接写库仍可写入非法字面量，
但读取时会 fail-closed 报错而非静默取默认值。

`param_value` 为什么可空
----------------------
`NULL` = **未显式设置**，此时取值回落到 `default_value`。
这不是"空值容忍"，而是 `05 §5` 同时要求"默认值"与"当前值"两个概念：
若不允许可空，就只能把默认值复制一份到当前值里，
于是"默认值被改了，但没人重新设置过当前值"这件事将无法表达。

与 Dictionary 的分离（`05 §5` 第一句 + `PHASE-007-DICTIONARY.md`）
---------------------------------------------------------------
参数与字典是**两张表、两个服务、两组端点**：

| | 字典 | 系统参数 |
|---|---|---|
| 用途 | 枚举展示 / 取值域 | 运行时配置 |
| 结构 | 父子两表 | 单表 |
| 读取方式 | 按 `dict_code` 取一整组 | 按 `param_key` 取**一个类型化标量** |

刻意**不做**"把参数塞进字典项"的实现（那会让 `GET /dicts/{code}`
同时成为配置读取入口，权限与缓存语义立刻混在一起）。
"""

from __future__ import annotations

from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin
from app.db.types import enum_type
from app.models.enums import SystemParamStatus, SystemParamType

#: 参数键长度（INTERIM；Spec 未定义）。
PARAM_KEY_LENGTH = 128
#: 参数名称长度。
PARAM_NAME_LENGTH = 128
#: 参数字面量长度上限（INTERIM；见 `SystemParameterService` 的解析规则）。
PARAM_VALUE_LENGTH = 512
#: 描述长度（与 `roles.description` 一致）。
DESCRIPTION_LENGTH = 255


class SysParam(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """系统参数（Spec `05 §5`）。

    `param_key` 是对外的稳定标识（如 `mfa.required_default`），
    服务层不允许通过 `PUT` 修改它 —— 改键等于换一个参数，
    而引用它的代码（例如 MFA 策略解析）不会跟着变，结果是
    "配置还在、却不再生效"这类最难排查的故障。

    状态语义（INTERIM-7-02）：`DISABLED` 的参数**读取方必须 fail-closed**，
    不得静默回落到默认值。详见 `app/services/system_param.py`。
    """

    __tablename__ = "sys_params"

    param_key: Mapped[str] = mapped_column(
        String(PARAM_KEY_LENGTH),
        nullable=False,
        comment="参数键；逻辑删除感知唯一（partial unique index），对外稳定标识，不可修改",
    )
    param_name: Mapped[str] = mapped_column(
        String(PARAM_NAME_LENGTH),
        nullable=False,
        comment="参数名称（供后台展示）",
    )
    param_type: Mapped[SystemParamType] = mapped_column(
        enum_type(SystemParamType, name="param_type", length=16),
        nullable=False,
        comment="类型 STRING / INT / BOOL（Spec 05 §5 要求参数必须有类型）",
    )
    param_value: Mapped[str | None] = mapped_column(
        String(PARAM_VALUE_LENGTH),
        nullable=True,
        comment="当前值（字面量）；NULL 表示未显式设置，回落到 default_value",
    )
    default_value: Mapped[str] = mapped_column(
        String(PARAM_VALUE_LENGTH),
        nullable=False,
        comment="默认值（字面量）；param_value 为 NULL 时生效",
    )
    status: Mapped[SystemParamStatus] = mapped_column(
        enum_type(SystemParamStatus),
        nullable=False,
        default=SystemParamStatus.ACTIVE,
        comment="参数状态 ACTIVE / DISABLED；DISABLED 时读取方 fail-closed",
    )
    description: Mapped[str | None] = mapped_column(
        String(DESCRIPTION_LENGTH),
        nullable=True,
        comment="参数描述",
    )

    __table_args__ = (
        Index(
            "uq_sys_params_param_key_active",
            "param_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


__all__ = [
    "DESCRIPTION_LENGTH",
    "PARAM_KEY_LENGTH",
    "PARAM_NAME_LENGTH",
    "PARAM_VALUE_LENGTH",
    "SysParam",
]
