"""角色 API 契约（Pydantic DTO）。

Frozen / 已裁定依据
------------------
- Spec `03 §2`：Role 字段 id / role_code / role_name / status / description /
  created_at / updated_at / deleted_at。
- Spec `08 §7`：`GET/POST /roles`、`PUT /roles/{id}`、`POST /roles/{id}/delete`、
  `GET /roles/{id}/permissions`、
  `PUT /roles/{id}/permissions/{pages,menus,buttons,apis,fields}`、
  `GET/PUT /roles/{id}/data-scope`。
- Spec `03 §10` / `00 §3`：数据范围五值；字段权限四值。
- Spec `03 §11`：权限预览（有效权限 / 来源角色 / 继承链 / Data Scope / Field）。
- Spec `07 §2` / `00 §6`：JSON 中 BIGINT 业务 ID 一律为字符串。
- 人类裁定：分页请求 `pageNum` + `pageSize`，响应 `{list,total,pageNum,pageSize}`。
- **DD-20 已冻结**：授权请求体为整体替换
  `{"resourceIds": [...]}`；字段授权为
  `{"fields": [{"resourceId": "...", "accessLevel": "READ_ONLY"}]}`。
- **DD-06 已冻结**：字段等级取值 VISIBLE / HIDDEN / READ_ONLY / EDITABLE。

本 Phase 边界
------------
HTTP 端点层按既定做法**暂不挂载**（认证在 Phase 4 落地后才有 `CurrentActor`；
资源端点属 Phase 8）。本模块只交付契约。

`list` 字段名遮蔽内建 `list` 的注意事项
------------------------------------
分页响应的 `list` 字段名由人类裁定固定。字段名会遮蔽内建 `list`，
因此注解与默认工厂都必须显式写 `builtins.list`，
否则 Pydantic 解析注解时会在类命名空间取到 `FieldInfo` 并报
"'FieldInfo' object is not subscriptable"（Phase 2 FIX-003 的真实教训）。
"""

from __future__ import annotations

import builtins
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.scope import DataScope
from app.models.enums import FieldAccessLevel, RoleStatus
from app.schemas.types import SnowflakeId

_PAGE_SIZE_MAX = 100

#: Spec 未冻结字段长度，此处与 model 列长度保持一致（INTERIM 技术取值）。
_ROLE_CODE_MAX = 64
_ROLE_NAME_MAX = 128
_DESCRIPTION_MAX = 255


class RoleSummaryResponse(BaseModel):
    """角色摘要（用户角色关联接口使用）。"""

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId = Field(description="角色 ID（JSON 为字符串）")
    role_code: str = Field(description="角色编码；SUPER_ADMIN 等特权角色以此为标识")
    role_name: str
    status: RoleStatus


class RoleResponse(BaseModel):
    """角色实体响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    role_code: str
    role_name: str
    status: RoleStatus
    description: str | None = None
    data_scope: DataScope = Field(description="数据范围策略（Spec 03 §10）")
    created_at: datetime
    updated_at: datetime


class RoleListQuery(BaseModel):
    """`GET /roles` 查询参数。"""

    model_config = ConfigDict(extra="forbid")

    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=_PAGE_SIZE_MAX)
    keyword: str | None = Field(default=None, max_length=_ROLE_CODE_MAX)
    status: RoleStatus | None = None


class RoleCreateRequest(BaseModel):
    """`POST /roles` 请求体。

    有意**不包含** `data_scope`：数据范围走独立的
    `GET/PUT /roles/{id}/data-scope`，从而保证 ROLE_DATA_SCOPE_UPDATE
    审计不可被绕过（与 `UserUpdateRequest` 排除 status 同一思路）。
    """

    model_config = ConfigDict(extra="forbid")

    role_code: str = Field(min_length=1, max_length=_ROLE_CODE_MAX)
    role_name: str = Field(min_length=1, max_length=_ROLE_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)
    status: RoleStatus = Field(default=RoleStatus.ACTIVE)


class RoleUpdateRequest(BaseModel):
    """`PUT /roles/{id}` 请求体。

    有意**不包含** `role_code` 与 `data_scope`（见 `RoleService` 的模块说明）：
    编码是角色的稳定标识，改码会影响 SUPER_ADMIN 判定与审计检索。
    """

    model_config = ConfigDict(extra="forbid")

    role_name: str | None = Field(default=None, min_length=1, max_length=_ROLE_NAME_MAX)
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)
    status: RoleStatus | None = None


class RolePageResponse(BaseModel):
    """`GET /roles` 分页响应。"""

    model_config = ConfigDict(from_attributes=True)

    list: builtins.list[RoleResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class RoleDataScopeRequest(BaseModel):
    """`PUT /roles/{id}/data-scope` 请求体。

    `department_ids` 仅在 `data_scope = CUSTOM` 时允许非空；
    其余策略携带非空集合会被服务层拒绝（避免"以为已限定、实际未限定"）。
    """

    model_config = ConfigDict(extra="forbid")

    data_scope: DataScope = Field(
        description="ALL / DEPARTMENT / DEPARTMENT_CHILDREN / SELF / CUSTOM"
    )
    department_ids: list[SnowflakeId] = Field(
        default_factory=list,
        description="仅 CUSTOM 时有效；非 CUSTOM 必须为空",
    )


class RoleDataScopeResponse(BaseModel):
    """`GET/PUT /roles/{id}/data-scope` 响应。"""

    role_id: SnowflakeId
    data_scope: DataScope
    department_ids: list[SnowflakeId] = Field(
        default_factory=list,
        description="CUSTOM 的部门集合；非 CUSTOM 恒为空数组（不留残留配置）",
    )


class RolePermissionIdsRequest(BaseModel):
    """四类二元权限的整体替换请求体（DD-20 冻结）。

    适用于 `PUT /roles/{id}/permissions/{pages,menus,buttons,apis}`。
    空数组表示**清空该类别的全部授权**（其余类别不受影响）。
    """

    model_config = ConfigDict(extra="forbid")

    resourceIds: list[SnowflakeId] = Field(
        default_factory=list,
        description="替换后的完整资源 ID 集合；仅影响该类别",
    )


class RoleFieldPermissionItem(BaseModel):
    """单个字段的授权条目（DD-06 冻结：携带四级取值）。"""

    model_config = ConfigDict(extra="forbid")

    resourceId: SnowflakeId = Field(description="FIELD 资源 ID")
    accessLevel: FieldAccessLevel = Field(description="VISIBLE / HIDDEN / READ_ONLY / EDITABLE")


class RoleFieldPermissionsRequest(BaseModel):
    """`PUT /roles/{id}/permissions/fields` 请求体。"""

    model_config = ConfigDict(extra="forbid")

    fields: list[RoleFieldPermissionItem] = Field(
        default_factory=list,
        description="替换后的完整字段授权集合；空数组表示清空",
    )


class RolePermissionViewResponse(BaseModel):
    """`GET /roles/{id}/permissions` 响应。

    `field_levels` 的键为 FIELD 资源 ID 的字符串形式
    （JSON 对象的键只能是字符串，而业务 ID 也必须序列化为字符串）。
    """

    role_id: SnowflakeId
    page_ids: list[SnowflakeId] = Field(default_factory=list)
    menu_ids: list[SnowflakeId] = Field(default_factory=list)
    button_ids: list[SnowflakeId] = Field(default_factory=list)
    api_ids: list[SnowflakeId] = Field(default_factory=list)
    field_levels: dict[str, FieldAccessLevel] = Field(
        default_factory=dict, description="FIELD 资源 ID → 权限等级"
    )


class RoleInheritanceGrantRequest(BaseModel):
    """`POST /roles/{id}/inheritance` 请求体：`{id}` 为**子角色**（权限获得方）。"""

    model_config = ConfigDict(extra="forbid")

    parent_role_id: SnowflakeId = Field(description="被继承的角色（权限提供方）")


class RoleInheritanceResponse(BaseModel):
    """继承链响应（`03 §11` 权限预览的一部分）。"""

    role_id: SnowflakeId
    parent_role_ids: list[SnowflakeId] = Field(default_factory=list, description="直接父角色")
    child_role_ids: list[SnowflakeId] = Field(default_factory=list, description="直接子角色")
    ancestor_role_ids: list[SnowflakeId] = Field(
        default_factory=list, description="全部祖先角色（继承链）"
    )


class PermissionPreviewResponse(BaseModel):
    """`GET /users/{id}/permission-preview` 响应（Spec `03 §11`）。

    只输出**结论与来源**，不输出任何敏感字段。
    """

    user_id: SnowflakeId
    direct_role_ids: list[SnowflakeId] = Field(default_factory=list)
    inherited_role_ids: list[SnowflakeId] = Field(default_factory=list)
    page_ids: list[SnowflakeId] = Field(default_factory=list)
    menu_ids: list[SnowflakeId] = Field(default_factory=list)
    button_ids: list[SnowflakeId] = Field(default_factory=list)
    api_ids: list[SnowflakeId] = Field(default_factory=list)
    field_levels: dict[str, FieldAccessLevel] = Field(default_factory=dict)
    data_scope: DataScope
    source_scopes: list[DataScope] = Field(
        default_factory=list, description="参与求并的原始策略集合（DD-19）"
    )
    scope_department_ids: list[SnowflakeId] | None = Field(
        default=None, description="求并后的部门集合；null 表示不限制（ALL）"
    )
    include_self: bool = Field(description="是否在部门集合之外额外包含本人（DD-19）")
    inheritance_edges: list[tuple[SnowflakeId, SnowflakeId]] = Field(
        default_factory=list, description="(parent_role_id, child_role_id) 继承边"
    )
    version: int = Field(description="permission version（DD-04 未冻结其缓存语义）")


__all__ = [
    "PermissionPreviewResponse",
    "RoleCreateRequest",
    "RoleDataScopeRequest",
    "RoleDataScopeResponse",
    "RoleFieldPermissionItem",
    "RoleFieldPermissionsRequest",
    "RoleInheritanceGrantRequest",
    "RoleInheritanceResponse",
    "RoleListQuery",
    "RolePageResponse",
    "RolePermissionIdsRequest",
    "RolePermissionViewResponse",
    "RoleResponse",
    "RoleSummaryResponse",
    "RoleUpdateRequest",
]
