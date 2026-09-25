"""字典模型（Spec `05 §1`~`§3`）。

Frozen 依据
-----------
- Spec `05 §1`：模型为 `sys_dict_type └── sys_dict_item`（两表，父子）。
- Spec `05 §2` `sys_dict_type` 字段：id / dict_code / dict_name / description /
  status / created_at / updated_at / deleted_at。
- Spec `05 §3` `sys_dict_item` 字段：id / dict_type_id / item_label / item_value /
  item_code / sort_order / status / is_default / description /
  created_at / updated_at / deleted_at。
- Spec `05 §3`：**"同一 dict type 下 item_value 必须支持软删除感知的唯一性"**。
- Spec `00 §6` / `07 §3`：默认逻辑删除；唯一约束必须考虑逻辑删除。
- Spec `07 §9`：必须检查 FK / index / unique / soft-delete-aware unique。
- Spec `11 §3`："字典唯一值"是并发保护的重点对象。

表名为什么带 `sys_` 前缀
----------------------
`05 §2` 直接给出 `sys_dict_type` / `sys_dict_item`，属冻结表名。
系统参数表（`05 §5`）Spec **未命名**，沿用同一前缀取 `sys_params`
（登记 INTERIM-7-01；见 `app/models/param.py`）。

索引与约束设计
-------------
`sys_dict_type`：

| 名称（partial unique 条件均为 `deleted_at IS NULL`） | 作用 |
|---|---|
| `uq_sys_dict_type_dict_code_active` | 编码唯一；允许逻辑删除后用同一编码重建 |
| `ix_sys_dict_type_deleted_at` | 来自 `SoftDeleteMixin` |

`sys_dict_item`：

- `ix_sys_dict_item_dict_type_id`：按字典查项（公开查询与列表的主路径）；
- `uq_sys_dict_item_type_value_active`(`dict_type_id`,`item_value`)：
  `05 §3` 的**软删除感知唯一性**；
- `uq_sys_dict_item_type_default_active`(`dict_type_id`) where `is_default`：
  每个字典**至多一个**默认项；
- `ix_sys_dict_item_deleted_at`：来自 `SoftDeleteMixin`。

"至多一个默认项"为什么也放在数据库层
----------------------------------
Spec 只规定 `is_default` 这个字段存在，没有规定"能否有多个默认项"。
一个字典存在两个默认项，在业务上是自相矛盾的数据（调用方无法回答
"默认取哪一个"）。服务层在设置默认项时会把同字典其他行置为非默认，
但**服务层不是唯一写入路径**（迁移、运维脚本、将来的导入任务都会写库），
因此再加一条 partial unique index 作为兜底：它把"自相矛盾的数据"
变成一次明确的写入失败，而不是一条永远解释不清的记录。
代价是"同字典两个默认项"会被数据库拒绝（409 语义），已登记为
INTERIM-7-03 —— 若人类裁定允许多默认项，改动的只是一条索引。

列长度说明
---------
Spec 未定义任何字段长度，此处为 INTERIM 技术取值，不表达业务规则；
`description` 取 255 与 `roles` / `departments` 一致。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin
from app.db.types import enum_type
from app.models.enums import DictStatus

#: 字典编码长度（INTERIM，见模块说明）。
DICT_CODE_LENGTH = 64
#: 字典名称长度。
DICT_NAME_LENGTH = 128
#: 字典项展示文案长度。
ITEM_LABEL_LENGTH = 128
#: 字典项取值长度 —— 会被业务数据回传，故与编码同量级。
ITEM_VALUE_LENGTH = 128
#: 字典项编码长度。
ITEM_CODE_LENGTH = 64
#: 描述长度（与 `roles.description` 一致）。
DESCRIPTION_LENGTH = 255


class SysDictType(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """字典类型（Spec `05 §2`）。

    一个字典类型代表一组枚举：`gender` / `user_status` / …
    `dict_code` 是**对外的稳定标识**（公开查询按它取字典），
    因此服务层不允许通过 `PUT` 修改它（与 `role_code` 同口径）——
    改码会让已经在用该编码的前端与调用方静默失效。

    不复用 `PermissionStatus` 之类的枚举：见 `app.models.enums.DictStatus`。
    """

    __tablename__ = "sys_dict_type"

    dict_code: Mapped[str] = mapped_column(
        String(DICT_CODE_LENGTH),
        nullable=False,
        comment="字典编码；逻辑删除感知唯一（partial unique index），对外稳定标识，不可修改",
    )
    dict_name: Mapped[str] = mapped_column(
        String(DICT_NAME_LENGTH),
        nullable=False,
        comment="字典名称",
    )
    description: Mapped[str | None] = mapped_column(
        String(DESCRIPTION_LENGTH),
        nullable=True,
        comment="字典描述",
    )
    status: Mapped[DictStatus] = mapped_column(
        enum_type(DictStatus),
        nullable=False,
        default=DictStatus.ACTIVE,
        comment="字典状态 ACTIVE / DISABLED；DISABLED 不参与公开查询",
    )

    __table_args__ = (
        Index(
            "uq_sys_dict_type_dict_code_active",
            "dict_code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class SysDictItem(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """字典项（Spec `05 §3`）。

    `item_value` 是**存进业务数据的值**，`item_label` 是展示文案，
    `item_code` 是给代码用的可读标识 —— 三者不可互相替代，
    因此 Spec 同时列出后不合并、不推导（不做"没有 item_code 就用
    item_value 代替"之类的隐式回落：那会让同一条数据在不同字典下
    含义不同）。

    `is_default` 表示"该字典的默认项"，见模块说明中的唯一性约束。
    本表的删除是**逻辑删除**：`deleted_at IS NULL` 的行才是"存在的项"，
    因此同一 `item_value` 可以在删除后重新创建。
    """

    __tablename__ = "sys_dict_item"

    dict_type_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sys_dict_type.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="所属字典类型 ID",
    )
    item_label: Mapped[str] = mapped_column(
        String(ITEM_LABEL_LENGTH),
        nullable=False,
        comment="展示文案",
    )
    item_value: Mapped[str] = mapped_column(
        String(ITEM_VALUE_LENGTH),
        nullable=False,
        comment="取值；同字典内软删除感知唯一（partial unique index）",
    )
    item_code: Mapped[str] = mapped_column(
        String(ITEM_CODE_LENGTH),
        nullable=False,
        comment="编码（供代码引用的可读标识）",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="排序值（升序）；Spec 未规定取值范围，故不加 CHECK",
    )
    status: Mapped[DictStatus] = mapped_column(
        enum_type(DictStatus),
        nullable=False,
        default=DictStatus.ACTIVE,
        comment="字典项状态 ACTIVE / DISABLED；DISABLED 不下发",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否默认项；每个字典至多一个（partial unique index）",
    )
    description: Mapped[str | None] = mapped_column(
        String(DESCRIPTION_LENGTH),
        nullable=True,
        comment="字典项描述",
    )

    __table_args__ = (
        Index(
            "uq_sys_dict_item_type_value_active",
            "dict_type_id",
            "item_value",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_sys_dict_item_type_default_active",
            "dict_type_id",
            unique=True,
            postgresql_where=text("is_default AND deleted_at IS NULL"),
        ),
    )


__all__ = [
    "DESCRIPTION_LENGTH",
    "DICT_CODE_LENGTH",
    "DICT_NAME_LENGTH",
    "ITEM_CODE_LENGTH",
    "ITEM_LABEL_LENGTH",
    "ITEM_VALUE_LENGTH",
    "SysDictItem",
    "SysDictType",
]
