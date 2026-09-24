"""部门 API 契约（Pydantic DTO）。

Frozen / 已裁定依据
------------------
- Spec `08 §6`：`GET /departments/tree`、`POST /departments`、
  `PUT /departments/{id}`、`POST /departments/{id}/disable`
  （人类裁定补齐 `POST /departments/{id}/delete`）。
- Spec `08 §2`：`/api/v1/admin` 前缀；响应信封 `{code, message, data}`。
- Spec `07 §2` / `00 §6`：API JSON 中 BIGINT 业务 ID 一律为**字符串**。
- Spec `02 §1`：创建 / 修改 / 禁用 / 逻辑删除 / 树查询。

本 Phase 边界
------------
HTTP 端点层按人类裁定**暂不挂载**（认证尚未实现，Phase 4 才可能有 Actor）。
因此本模块只交付**契约**（请求 / 响应模型），
不含任何 FastAPI 路由装饰器，也不引入对 Service 的调用。

`parent_id` 的"未提供 vs 显式置空"
--------------------------------
`PUT /departments/{id}` 允许把部门移动成根节点（`parent_id = null`），
这与"请求里根本没写 `parent_id`（不改动）"是两种不同语义。

本模块用 Pydantic 原生的 `exclude_unset` 区分：
端点层调用 `model_dump(exclude_unset=True)`，未提供的字段不会出现在 kwargs 中，
于是 Service 的 `_UNSET` 哨兵默认值自然生效 ——
**无需**在 schema 层依赖 Service 的私有哨兵类型。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DepartmentStatus
from app.schemas.types import SnowflakeId

#: Spec 未冻结字段长度，此处与 model 列长度保持一致（INTERIM 技术取值）。
_DEPARTMENT_CODE_MAX = 64
_DEPARTMENT_NAME_MAX = 128


class DepartmentCreateRequest(BaseModel):
    """`POST /departments` 请求体。"""

    model_config = ConfigDict(extra="forbid")

    department_code: str = Field(
        min_length=1,
        max_length=_DEPARTMENT_CODE_MAX,
        description="部门编码；逻辑删除感知唯一",
    )
    department_name: str = Field(
        min_length=1,
        max_length=_DEPARTMENT_NAME_MAX,
        description="部门名称",
    )
    parent_id: SnowflakeId | None = Field(
        default=None,
        description="父部门 ID；null 表示创建根部门（仅全局数据范围允许）",
    )


class DepartmentUpdateRequest(BaseModel):
    """`PUT /departments/{id}` 请求体。

    有意**不包含** `status`：禁用必须走 `POST /departments/{id}/disable`，
    以保证 `DEPARTMENT_DISABLE` 审计动作不可被绕过（Spec `10 §8`）。
    """

    model_config = ConfigDict(extra="forbid")

    department_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=_DEPARTMENT_CODE_MAX,
        description="部门编码；null / 缺省表示不修改",
    )
    department_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=_DEPARTMENT_NAME_MAX,
        description="部门名称；null / 缺省表示不修改",
    )
    parent_id: SnowflakeId | None = Field(
        default=None,
        description="父部门 ID；显式 null 表示移动到根（未提供则不改动）",
    )


class DepartmentResponse(BaseModel):
    """部门实体响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId = Field(description="部门 ID（JSON 为字符串）")
    parent_id: SnowflakeId | None = Field(default=None, description="父部门 ID")
    department_code: str
    department_name: str
    status: DepartmentStatus
    created_at: datetime
    updated_at: datetime


class DepartmentTreeNodeResponse(BaseModel):
    """部门树节点响应（`GET /departments/tree`）。"""

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId = Field(description="部门 ID（JSON 为字符串）")
    parent_id: SnowflakeId | None = Field(default=None, description="父部门 ID")
    department_code: str
    department_name: str
    status: DepartmentStatus
    children: list[DepartmentTreeNodeResponse] = Field(default_factory=list)


DepartmentTreeNodeResponse.model_rebuild()

__all__ = [
    "DepartmentCreateRequest",
    "DepartmentResponse",
    "DepartmentTreeNodeResponse",
    "DepartmentUpdateRequest",
]
