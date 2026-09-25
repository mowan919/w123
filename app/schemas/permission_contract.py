"""前端动态权限契约（`GET /auth/permissions`）。

Frozen / 已裁定依据
------------------
- Spec `09 §2`：`GET /auth/permissions` 应返回当前用户**有效权限**，
  至少能表达 pages / menus / buttons / APIs / fields / data scopes /
  permission version。
- Spec `00 §3` / `03 §1`：权限链 User → Role → 继承 → Page → Menu →
  Button → API → Field → Data Scope。
- Spec `00 §1#4` / `03 §6` / `09 §4`：一个 Menu 可关联**多个** Page；
  Menu 负责导航组织，Page 负责页面访问权限。
- Spec `09 §3`："前端隐藏页面 = 安全"被明令禁止 —— 前端只消费本契约做
  渲染，真正的边界仍是后端 API authorization（`08 §10`）。
- Spec `09 §5`：按钮按 Button Permission 显示/隐藏，但其对应 API 必须**再次**授权
  —— 因此本契约输出按钮只影响可见性，绝不携带"该接口已授权"的含义。
- Spec `09 §6`：字段权限四级，前端据 Field Permission 处理 HIDDEN /
  READ_ONLY / EDITABLE / VISIBLE。
- Spec `09 §7`：权限变化立即生效（本 Phase 以"实时计算、无缓存"满足）。
- Spec `07 §2` / `00 §6`：JSON 中 BIGINT 业务 ID 一律序列化为**字符串**。

命名约定
-------
响应 DTO 统一 `snake_case`（与 `PermissionPreviewResponse` /
`RolePermissionViewResponse` 一致）；查询与请求体才用 camelCase。

为什么 `data_scope.policy` 可为 `null`
------------------------------------
`DataScope` 是**角色上的配置值**。用户没有任何有效角色时，
既不存在某个策略，也不该凭空挑一个值来说 —— 因此用 `null` 表达
"无任何有效策略"，并配合 `department_ids = []` 表达"拒绝一切"。
把它写成 `SELF` 会是**误导性诊断**（看起来像配了最窄策略，
实际是没配），本模块拒绝这种"看起来有值"的表示
（见 `docs/DESIGN-DECISIONS.md` §15 对 DD-21 的处理）。

`department_ids` 的三态
---------------------
| 传值 | 含义 |
|---|---|
| `null` | 部门维度**不限制**（仅 ALL / SUPER_ADMIN） |
| `[]` | 什么都不允许看见（fail-closed 的空集合） |
| 非空数组 | 允许的部门集合（DEPARTMENT_CHILDREN 已展开为含后代的集合） |
"""

from __future__ import annotations

import builtins

from pydantic import BaseModel, ConfigDict, Field

from app.core.scope import DataScope
from app.models.enums import FieldAccessLevel
from app.schemas.types import SnowflakeId


class PermissionPageItem(BaseModel):
    """可访问的**页面**（`03 §5`）。

    `route_path` / `component_path` 是前端**动态生成路由**所需的全部信息
    （`09 §3`）：前端据此 `router.addRoute`，而不是在代码里硬编码路由表。
    """

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    code: str = Field(description="资源编码（前端稳定标识，权限变更后仍可比对）")
    name: str
    route_path: str | None = Field(default=None, description="PAGE 专属：前端路由路径")
    component_path: str | None = Field(default=None, description="PAGE 专属：前端组件路径")
    sort_order: int = 0


class PermissionMenuItem(BaseModel):
    """导航菜单（`03 §6` / `09 §4`）。

    `page_ids` 是**该菜单下已授权页面的交集** —— 即
    `菜单关联的 Page` ∩ `用户已授权 Page`。
    交集这一步必须由后端做：若把菜单关联的全部 Page 下发，
    前端就会渲染出指向"无权访问页面"的入口，而那正是
    `09 §3` 禁止的"前端隐藏页面 = 安全"陷阱的前置形态。

    `parent_id` 用于让前端还原导航层级；`icon` / `sort_order` 供渲染。

    后端**不**裁剪"没有任何可访问页面"的菜单：该菜单本身是被授权的资源，
    是否渲染空菜单属于前端渲染策略（`09 §3` 明确前端是消费方）。
    本契约只保证**下发的每一项都是已授权的**。
    """

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    code: str
    name: str
    icon: str | None = None
    parent_id: SnowflakeId | None = None
    sort_order: int = 0
    page_ids: builtins.list[SnowflakeId] = Field(
        default_factory=builtins.list,
        description="该菜单下用户可访问的 Page ID（已与授权集合求交）",
    )


class PermissionButtonItem(BaseModel):
    """页面内操作入口（`03 §7`）。

    `parent_id` 指向所属 PAGE，前端据此把按钮挂到对应页面/组件上。

    ⚠️ 本项只表达"入口是否可见"（`09 §5`）。对应 API 是否可调用，
    必须由后端在 `08 §10` 的授权判定中独立决定 —— 该信息**不在**本契约里
    （否则前端一旦被篡改/误读，就会把"没下发"解释成"没授权"或反之）。
    """

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    code: str
    name: str
    parent_id: SnowflakeId | None = Field(default=None, description="所属 PAGE 资源 ID")
    sort_order: int = 0


class PermissionApiItem(BaseModel):
    """后端接口授权（`03 §8`）。

    `api_method` / `api_path` 仅作**资源台账与前端展示**
    （DD-20 §5.1.3 冻结：真正的判权主键是 `code`，即声明式绑定里的
    `resource_code`）。前端**不得**用本列表做任何访问决策。
    """

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    code: str
    name: str
    api_method: str | None = None
    api_path: str | None = None
    parent_id: SnowflakeId | None = None


class PermissionFieldItem(BaseModel):
    """字段级策略（`03 §9` / `09 §6`）。

    `access_level` 是**多角色合并后的最终等级**（DD-06 冻结：最宽松者胜），
    由后端统一计算下发 —— 前端不得自行把多个角色的等级再合并一次。

    未出现在 `fields` 中的字段 = **没有任何授权记录**。调用方必须按
    HIDDEN 处理（fail-closed）：`09 §6` 要求"后端应避免在 HIDDEN 字段中
    无意返回敏感数据"，而"没查到策略"与"策略是 HIDDEN"在安全性上必须等价。
    """

    model_config = ConfigDict(from_attributes=True)

    id: SnowflakeId
    code: str
    field_key: str = Field(description="字段名（如 phone / email）")
    owner_resource_id: SnowflakeId | None = Field(
        default=None, description="字段所属 PAGE 资源 ID（DD-06 冻结）"
    )
    access_level: FieldAccessLevel


class PermissionDataScopeResponse(BaseModel):
    """有效数据范围（`03 §10` / `09 §2`）。"""

    policy: DataScope | None = Field(
        default=None,
        description="代表策略（多角色取最宽者）；null 表示无任何有效角色策略",
    )
    department_ids: builtins.list[SnowflakeId] | None = Field(
        default=None,
        description="可见部门集合；null 表示部门维度不限制，[] 表示全拒",
    )
    include_self: bool = Field(
        default=False,
        description="是否在部门集合之外额外包含本人（DD-19 的 include_self）",
    )


class PermissionContractResponse(BaseModel):
    """`GET /auth/permissions` 响应体（`09 §2` 的完整落地）。

    字段顺序与 `09 §2` 的清单一致，便于逐条对照验收。

    本响应**只包含权限元数据**，不包含任何用户敏感信息
    （无手机号 / 邮箱 / 口令 / 令牌 / MFA Secret）。
    """

    user_id: SnowflakeId
    is_super_admin: bool = Field(
        default=False,
        description="SUPER_ADMIN 走集中式 bypass（`10 §3`），其有效权限为全部资源",
    )
    direct_role_ids: builtins.list[SnowflakeId] = Field(default_factory=builtins.list)
    inherited_role_ids: builtins.list[SnowflakeId] = Field(
        default_factory=builtins.list, description="经角色继承展开得到的角色（DD-05）"
    )
    pages: builtins.list[PermissionPageItem] = Field(default_factory=builtins.list)
    menus: builtins.list[PermissionMenuItem] = Field(default_factory=builtins.list)
    buttons: builtins.list[PermissionButtonItem] = Field(default_factory=builtins.list)
    apis: builtins.list[PermissionApiItem] = Field(default_factory=builtins.list)
    fields: builtins.list[PermissionFieldItem] = Field(default_factory=builtins.list)
    data_scope: PermissionDataScopeResponse
    permission_version: int = Field(
        description="权限版本号（`09 §2`）；DD-04 未冻结其缓存语义，本 Phase 为实时计算"
    )


__all__ = [
    "PermissionApiItem",
    "PermissionButtonItem",
    "PermissionContractResponse",
    "PermissionDataScopeResponse",
    "PermissionFieldItem",
    "PermissionMenuItem",
    "PermissionPageItem",
]
