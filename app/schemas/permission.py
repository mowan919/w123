"""权限资源 API 契约（Pydantic DTO，DD-20 冻结的端点形状）。

Frozen / 已裁定依据
------------------
- Spec `03 §5~§9`：Page / Menu / Button / API / Field 五类资源语义。
- Spec `00 §1#4` / `03 §6` / `09 §4`：一个 Menu 可关联多个 Page；
  Menu 负责导航组织，Page 负责页面访问权限。
- Spec `09 §2`：`/auth/permissions` 输出 pages / menus / buttons / APIs /
  fields / data scopes / permission version。
- Spec `07 §2` / `00 §6`：JSON 中 BIGINT 业务 ID 一律为字符串。
- **DD-20 已冻结**（`08 §7` 原缺失的资源 CRUD 端点契约）：

```text
GET    /permission-resources?resourceType=&parentId=&keyword=&status=&pageNum=&pageSize=
POST   /permission-resources
GET    /permission-resources/{id}
PUT    /permission-resources/{id}
POST   /permission-resources/{id}/delete
GET    /permission-resources/tree?resourceType=MENU
GET    /permission-resources/{id}/pages
PUT    /permission-resources/{id}/pages
```

- **DD-06 已冻结**：FIELD 通过 `owner_resource_id` 归属 PAGE。

本 Phase 边界
------------
HTTP 端点层属 **Phase 8**（"权限资源 API / 前端动态权限 / 权限闭环"）。
本模块只交付契约，不含路由装饰器。

`parent_id` 的三态语义（查询参数）
------------------------------
`GET /permission-resources` 的 `parentId` 有三种含义，必须区分清楚：

| 传值 | 含义 |
|---|---|
| 不传（`null`） | 不按父节点过滤 |
| `"0"` | 只看顶级节点（`parent_id IS NULL`） |
| 具体 ID | 只看该父节点的直接子节点 |

用 `"0"` 而不是 `null` 表达"顶级"，是因为 `null` 已被占用为"不过滤"，
而 Snowflake ID 恒为正数，`0` 不可能与真实资源 ID 冲突。
"""

from __future__ import annotations

import builtins
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import HttpMethod, PermissionResourceType, PermissionStatus
from app.schemas.types import SnowflakeId

_PAGE_SIZE_MAX = 100

#: 与 model 列长度一致（INTERIM 技术取值；Spec 未冻结长度）。
_CODE_MAX = 128
_NAME_MAX = 128
_PATH_MAX = 255
_ICON_MAX = 64
_FIELD_KEY_MAX = 128


class PermissionResourceListQuery(BaseModel):
    """`GET /permission-resources` 查询参数（`parentId` 三态语义见模块说明）。"""

    model_config = ConfigDict(extra="forbid")

    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=_PAGE_SIZE_MAX)
    resourceType: PermissionResourceType | None = Field(default=None, description="按资源类型过滤")
    parentId: SnowflakeId | None = Field(
        default=None, description="父资源 ID；传 0 表示只看顶级，不传表示不过滤"
    )
    status: PermissionStatus | None = None
    keyword: str | None = Field(default=None, max_length=_CODE_MAX)


class PermissionResourceCreateRequest(BaseModel):
    """`POST /permission-resources` 请求体。

    类型专属字段由服务层按 DD-20 冻结的形状规则校验
    （与数据库 CHECK 同一份规则），因此这里不做互斥校验，
    避免在 schema 与 service 两处各写一套形状规则而产生漂移。
    """

    model_config = ConfigDict(extra="forbid")

    resource_type: PermissionResourceType
    resource_code: str = Field(min_length=1, max_length=_CODE_MAX)
    resource_name: str = Field(min_length=1, max_length=_NAME_MAX)
    parent_id: SnowflakeId | None = Field(default=None, description="父资源；仅 MENU / API 可设")
    sort_order: int = Field(default=0, ge=0)
    status: PermissionStatus = Field(default=PermissionStatus.ACTIVE)

    # ---- PAGE 专属 ----
    route_path: str | None = Field(default=None, max_length=_PATH_MAX)
    component_path: str | None = Field(default=None, max_length=_PATH_MAX)
    # ---- MENU 专属 ----
    icon: str | None = Field(default=None, max_length=_ICON_MAX)
    # ---- API 专属 ----
    api_method: HttpMethod | None = None
    api_path: str | None = Field(default=None, max_length=_PATH_MAX)
    # ---- FIELD 专属 ----
    field_key: str | None = Field(default=None, max_length=_FIELD_KEY_MAX)
    owner_resource_id: SnowflakeId | None = Field(
        default=None, description="FIELD 归属的 PAGE 资源 ID"
    )


class PermissionResourceUpdateRequest(BaseModel):
    """`PUT /permission-resources/{id}` 请求体。

    有意**不包含** `resource_type` / `resource_code` / `parent_id` /
    `owner_resource_id`：

    - 改类型等于把已有角色授权静默重新解释成另一类权限（权限放大路径）；
    - 编码是资源在审计与前端契约中的稳定标识；
    - 调整树形归属需要连带校验子树形状与授权影响，属于独立的"移动资源"操作，
      不在 DD-20 冻结的端点范围内。
    """

    model_config = ConfigDict(extra="forbid")

    resource_name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    sort_order: int | None = Field(default=None, ge=0)
    status: PermissionStatus | None = None
    route_path: str | None = Field(default=None, max_length=_PATH_MAX)
    component_path: str | None = Field(default=None, max_length=_PATH_MAX)
    icon: str | None = Field(default=None, max_length=_ICON_MAX)
    api_method: HttpMethod | None = None
    api_path: str | None = Field(default=None, max_length=_PATH_MAX)
    field_key: str | None = Field(default=None, max_length=_FIELD_KEY_MAX)


class PermissionResourceResponse(BaseModel):
    """权限资源实体响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    resource_type: PermissionResourceType
    resource_code: str
    resource_name: str
    parent_id: SnowflakeId | None = None
    sort_order: int
    status: PermissionStatus
    route_path: str | None = None
    component_path: str | None = None
    icon: str | None = None
    api_method: str | None = None
    api_path: str | None = None
    field_key: str | None = None
    owner_resource_id: SnowflakeId | None = None
    created_at: datetime
    updated_at: datetime


class PermissionResourcePageResponse(BaseModel):
    """`GET /permission-resources` 分页响应。"""

    model_config = ConfigDict(from_attributes=True)

    list: builtins.list[PermissionResourceResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class PermissionResourceTreeNodeResponse(BaseModel):
    """资源树节点（`GET /permission-resources/tree`）。

    自引用模型：`children` 递归嵌套。
    """

    resource: PermissionResourceResponse
    children: builtins.list[PermissionResourceTreeNodeResponse] = Field(
        default_factory=builtins.list
    )


class MenuPagesResponse(BaseModel):
    """`GET /permission-resources/{id}/pages` 响应。"""

    menu_id: SnowflakeId
    pages: builtins.list[PermissionResourceResponse] = Field(default_factory=builtins.list)


class MenuPagesUpdateRequest(BaseModel):
    """`PUT /permission-resources/{id}/pages` 请求体（整体替换，`00 §1#4`）。"""

    model_config = ConfigDict(extra="forbid")

    pageIds: list[SnowflakeId] = Field(
        default_factory=list,
        description="替换后的完整 Page ID 集合；空数组表示解除全部关联",
    )


#: 自引用模型需要显式重建（Pydantic v2 对前向引用的要求）。
PermissionResourceTreeNodeResponse.model_rebuild()


__all__ = [
    "MenuPagesResponse",
    "MenuPagesUpdateRequest",
    "PermissionResourceCreateRequest",
    "PermissionResourceListQuery",
    "PermissionResourcePageResponse",
    "PermissionResourceResponse",
    "PermissionResourceTreeNodeResponse",
    "PermissionResourceUpdateRequest",
]
