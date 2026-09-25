"""系统参数 API 契约（Pydantic DTO）。

Frozen / 已裁定依据
------------------
- Spec `05 §5`：参数必须有**类型 / 默认值 / 状态 / 描述**（与审计）。
- Spec `07 §2` / `00 §6`：API JSON 中 BIGINT 业务 ID 一律为**字符串**。
- 人类裁定：分页请求 `pageNum` + `pageSize`，响应 `{list, total, pageNum, pageSize}`。
- 端点路径未在 `08 §9` 定义 → INTERIM-7-04
  （见 `app/api/v1/endpoints/params.py` 的模块文档）。

三个字段语义必须写清楚
-------------------

1. `param_value` 可为 `null` → 表示**未显式设置**，生效值回落到 `default_value`。
2. `clear_value` 是**显式清空**当前值的开关。没有它，`param_value` 一旦被写过
   就永远回不到 `null`，"默认值"这个概念会失去落点。
   它与"未提供 `param_value`"必须可区分，因此用独立布尔字段而不是
   "传 null 即清空"（后者与"字段缺省"在 JSON 里无法区分）。
3. `effective_value` 是**只读的计算结果**（`param_value ?? default_value`），
   与 Pydantic 计算字段无关 —— 它在端点层由服务端算出后填入。
   下发它是因为"哪一个是生效值"属于**规则**：若让客户端自己取
   `param_value or default_value`，每个客户端都会各自实现一遍，
   而后端一旦改变回退规则（例如新增 `ENV` 层），客户端无法跟随。

`param_key` / `param_type` 不可修改
----------------------------------
`PUT` 请求体刻意**不含**这两个字段：键是被代码引用的标识符，
类型是参数与读取代码之间的契约。改它们不会报错，只会让"配置还在、
却不再生效"或"读取时才 fail-closed" —— 后者通常发生在登录路径上。
需要变更时：新建参数 + 迁移引用（与"角色改码"同口径）。
"""

from __future__ import annotations

import builtins
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SystemParamStatus, SystemParamType
from app.models.param import (
    DESCRIPTION_LENGTH,
    PARAM_KEY_LENGTH,
    PARAM_NAME_LENGTH,
    PARAM_VALUE_LENGTH,
)
from app.schemas.types import SnowflakeId

_PAGE_SIZE_MAX = 100


class SystemParamListQuery(BaseModel):
    """`GET /params` 查询参数。"""

    model_config = ConfigDict(extra="forbid")

    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=_PAGE_SIZE_MAX)
    keyword: str | None = Field(
        default=None, max_length=PARAM_NAME_LENGTH, description="按键或名称模糊匹配"
    )
    status: SystemParamStatus | None = None


class SystemParamCreateRequest(BaseModel):
    """`POST /params` 请求体。

    `default_value` 必填（`05 §5`："参数必须有…默认值"），
    且与 `param_value` 一样必须符合 `param_type`（写入侧即拦截，
    避免非法字面量入库后到读取侧才 fail-closed）。
    """

    model_config = ConfigDict(extra="forbid")

    param_key: str = Field(min_length=1, max_length=PARAM_KEY_LENGTH)
    param_name: str = Field(min_length=1, max_length=PARAM_NAME_LENGTH)
    param_type: SystemParamType = Field(description="STRING / INT / BOOL")
    default_value: str = Field(max_length=PARAM_VALUE_LENGTH)
    param_value: str | None = Field(default=None, max_length=PARAM_VALUE_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_LENGTH)
    status: SystemParamStatus = Field(default=SystemParamStatus.ACTIVE)


class SystemParamUpdateRequest(BaseModel):
    """`PUT /params/{id}` 请求体（不含 `param_key` / `param_type`，见模块文档）。"""

    model_config = ConfigDict(extra="forbid")

    param_name: str | None = Field(default=None, min_length=1, max_length=PARAM_NAME_LENGTH)
    default_value: str | None = Field(default=None, max_length=PARAM_VALUE_LENGTH)
    param_value: str | None = Field(default=None, max_length=PARAM_VALUE_LENGTH)
    clear_value: bool = Field(
        default=False,
        description="true=清空当前值（回落到 default_value）；与提供 param_value 互斥",
    )
    description: str | None = Field(default=None, max_length=DESCRIPTION_LENGTH)
    status: SystemParamStatus | None = None


class SystemParamResponse(BaseModel):
    """系统参数响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    param_key: str
    param_name: str
    param_type: SystemParamType
    param_value: str | None = Field(
        default=None, description="当前值；null 表示未显式设置，生效值 = default_value"
    )
    default_value: str
    effective_value: str = Field(
        description="生效值（param_value 非 null 则用它，否则 default_value）"
    )
    status: SystemParamStatus
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class SystemParamPageResponse(BaseModel):
    """`GET /params` 分页响应。"""

    model_config = ConfigDict(from_attributes=True)

    list: builtins.list[SystemParamResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


__all__ = [
    "SystemParamCreateRequest",
    "SystemParamListQuery",
    "SystemParamPageResponse",
    "SystemParamResponse",
    "SystemParamUpdateRequest",
]
