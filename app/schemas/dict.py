"""字典 API 契约（Pydantic DTO）。

Frozen / 已裁定依据
------------------
- Spec `05 §2` / `05 §3`：字典类型与字典项的字段（响应模型按此逐字段给出）。
- Spec `05 §4` / `08 §9`：管理端点与**公开查询**端点清单。
- Spec `07 §2` / `00 §6`：API JSON 中 BIGINT 业务 ID 一律为**字符串**。
- Spec `08 §2`：响应信封 `{code, message, data}`（由端点层统一包装）。
- 人类裁定：分页请求 `pageNum` + `pageSize`，响应 `{list, total, pageNum, pageSize}`。

两个刻意的不对称
--------------

1. **字典项的列表不用分页字段名**
   `GET /dicts/{id}/items` 不分页（理由见 `DictService.list_items`），
   因此响应体是 `{"items": [...]}` 而**不是** `{list, total, pageNum, pageSize}`。
   复用分页字段名会让调用方以为还存在 `total` / `pageNum`，只是没返回。

2. **公开查询不返回内部 ID**
   `05 §4` 的公开端点只规定路径，未规定响应体。这里刻意**不**下发
   `id` / `dict_type_id`：客户端渲染下拉框只需要展示文案与取值
   （并且它**应当**回传 `item_value` 而不是内部主键）。
   少下发一个内部标识符，就少一条"把内部主键当业务键用"的误用路径
   （业务键才是 `dict_code` / `item_value`）。

`list` 字段名遮蔽内建 `list` 的注意事项（沿用 `RolePageResponse` 的教训）
---------------------------------------------------------------------
注解与默认工厂都必须显式写 `builtins.list`，否则 Pydantic 解析注解时会在
类命名空间取到 `FieldInfo` 并报 "'FieldInfo' object is not subscriptable"。
"""

from __future__ import annotations

import builtins
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.dict import (
    DESCRIPTION_LENGTH,
    DICT_CODE_LENGTH,
    DICT_NAME_LENGTH,
    ITEM_CODE_LENGTH,
    ITEM_LABEL_LENGTH,
    ITEM_VALUE_LENGTH,
)
from app.models.enums import DictStatus
from app.schemas.types import SnowflakeId

_PAGE_SIZE_MAX = 100


class DictTypeListQuery(BaseModel):
    """`GET /dicts` 查询参数。"""

    model_config = ConfigDict(extra="forbid")

    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=_PAGE_SIZE_MAX)
    keyword: str | None = Field(
        default=None, max_length=DICT_NAME_LENGTH, description="按编码或名称模糊匹配"
    )
    status: DictStatus | None = None


class DictTypeCreateRequest(BaseModel):
    """`POST /dicts` 请求体。"""

    model_config = ConfigDict(extra="forbid")

    dict_code: str = Field(min_length=1, max_length=DICT_CODE_LENGTH)
    dict_name: str = Field(min_length=1, max_length=DICT_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_LENGTH)
    status: DictStatus = Field(default=DictStatus.ACTIVE)


class DictTypeUpdateRequest(BaseModel):
    """`PUT /dicts/{id}` 请求体。

    有意**不包含** `dict_code`：编码是对外稳定标识（公开查询按它取字典），
    改码会让调用方静默失效（与 `RoleUpdateRequest` 排除 `role_code` 同口径）。
    """

    model_config = ConfigDict(extra="forbid")

    dict_name: str | None = Field(default=None, min_length=1, max_length=DICT_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_LENGTH)
    status: DictStatus | None = None


class DictTypeResponse(BaseModel):
    """字典类型响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    dict_code: str
    dict_name: str
    description: str | None = None
    status: DictStatus
    created_at: datetime
    updated_at: datetime


class DictTypePageResponse(BaseModel):
    """`GET /dicts` 分页响应。"""

    model_config = ConfigDict(from_attributes=True)

    list: builtins.list[DictTypeResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class DictTypeDeleteResponse(BaseModel):
    """`DELETE /dicts/{id}` 响应。

    `deleted_item_count` 如实回报**级联逻辑删除**的字典项数量：
    级联是"自己的从属数据"清理（见 `DictService` 模块文档），
    但用户必须能在响应里看到它确实发生了。
    """

    id: SnowflakeId
    dict_code: str
    deleted_item_count: int = Field(description="本次级联逻辑删除的字典项数量")


class DictItemListQuery(BaseModel):
    """`GET /dicts/{id}/items` 查询参数。"""

    model_config = ConfigDict(extra="forbid")

    status: DictStatus | None = Field(
        default=None,
        description=(
            "null=返回全部项（含已停用，管理界面默认）；"
            "ACTIVE=只返回生效项。公开查询强制只下发生效项"
        ),
    )


class DictItemCreateRequest(BaseModel):
    """`POST /dicts/{id}/items` 请求体。"""

    model_config = ConfigDict(extra="forbid")

    item_label: str = Field(min_length=1, max_length=ITEM_LABEL_LENGTH)
    item_value: str = Field(min_length=1, max_length=ITEM_VALUE_LENGTH)
    item_code: str = Field(min_length=1, max_length=ITEM_CODE_LENGTH)
    sort_order: int = Field(default=0, description="排序值（升序）")
    status: DictStatus = Field(default=DictStatus.ACTIVE)
    is_default: bool = Field(default=False, description="是否该字典的默认项（全字典至多一个）")
    description: str | None = Field(default=None, max_length=DESCRIPTION_LENGTH)


class DictItemUpdateRequest(BaseModel):
    """`PUT /dicts/{id}/items/{itemId}` 请求体。"""

    model_config = ConfigDict(extra="forbid")

    item_label: str | None = Field(default=None, min_length=1, max_length=ITEM_LABEL_LENGTH)
    item_value: str | None = Field(default=None, min_length=1, max_length=ITEM_VALUE_LENGTH)
    item_code: str | None = Field(default=None, min_length=1, max_length=ITEM_CODE_LENGTH)
    sort_order: int | None = None
    status: DictStatus | None = None
    is_default: bool | None = None
    description: str | None = Field(default=None, max_length=DESCRIPTION_LENGTH)


class DictItemResponse(BaseModel):
    """字典项响应（管理侧，含内部 ID）。"""

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    dict_type_id: SnowflakeId
    item_label: str
    item_value: str
    item_code: str
    sort_order: int
    status: DictStatus
    is_default: bool
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class DictItemListResponse(BaseModel):
    """`GET /dicts/{id}/items` 响应（**不分页**，见模块文档）。"""

    items: builtins.list[DictItemResponse] = Field(default_factory=builtins.list)


class PublicDictItemResponse(BaseModel):
    """公开查询中的单个字典项（**不含内部 ID**，见模块文档）。"""

    model_config = ConfigDict(from_attributes=True)

    item_label: str
    item_value: str = Field(description="存进业务数据的取值；客户端应回传它而不是内部 ID")
    item_code: str
    sort_order: int
    is_default: bool
    description: str | None = None


class PublicDictResponse(BaseModel):
    """`GET /api/v1/dicts/{dictCode}` 响应（`05 §4`）。

    只包含 `ACTIVE` 的字典项 —— 已停用与已删除的项不下发，
    且两者的不可见性对外无法区分（不暴露停用状态）。
    """

    model_config = ConfigDict(from_attributes=True)

    dict_code: str
    dict_name: str
    description: str | None = None
    items: builtins.list[PublicDictItemResponse] = Field(default_factory=builtins.list)


__all__ = [
    "DictItemCreateRequest",
    "DictItemListQuery",
    "DictItemListResponse",
    "DictItemResponse",
    "DictItemUpdateRequest",
    "DictTypeCreateRequest",
    "DictTypeDeleteResponse",
    "DictTypeListQuery",
    "DictTypePageResponse",
    "DictTypeResponse",
    "DictTypeUpdateRequest",
    "PublicDictItemResponse",
    "PublicDictResponse",
]
