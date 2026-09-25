"""前端动态权限契约服务（Phase 8 / Spec `09`）。

职责
----
把"有效权限"（`EffectivePermissionService` 算出的 `PermissionContext`）
翻译成**前端可直接消费**的权限契约：

```text
PermissionContext（授权事实：角色 / 资源 ID / 字段等级 / 范围）
        ↓  本服务（补全资源元数据 + 求交 + 定序）
pages / menus(→pages) / buttons / apis / fields / data_scope / version
```

为什么必须单独一层
----------------
`PermissionContext` 只有**资源 ID 集合**，没有 `route_path` / `component_path` /
`icon` / `parent_id`，前端拿不到"该生成什么路由与导航"。反过来，
把这些元数据塞进 `PermissionContext` 会把"授权计算"与"展示契约"耦合成一个
巨型结构：授权引擎每次判权都要多查一遍资源表。

因此分工明确：
- `EffectivePermissionService` = **授权事实**（判权也用它，是安全路径）；
- `PermissionContractService` = **展示契约**（只在 `/auth/permissions` 读路径使用）。

SUPER_ADMIN 的表达（JUDGMENT-8-01）
--------------------------------
`10 §3` 冻结了 SUPER_ADMIN 的**集中式 bypass**：`has_api_permission` 直接放行。
因此超管的"有效权限"在事实层面就是**全部资源**。若这里仍按
`role_permissions` 逐条读取，超管将得到**空集合** —— 前端渲染出一个空后台，
而真实授权是"全部"。那不是保守，而是**对授权状态的错误表述**
（且会让平台无法通过界面自助管理）。

所以：`is_super_admin == True` 时输出**全部 ACTIVE 资源**。

**字段权限刻意不做 bypass**：后端**没有任何**字段级 bypass
（`field_policies` 的消费方只有本契约），若超管在这里额外得到"全部字段可编辑"，
前端就会展示出后端实际并不承认的字段能力 —— 契约与行为不一致，
比"少显示"危险得多。因此字段策略对所有用户一视同仁地按
"角色授权 + 最宽松者胜（DD-06）"输出；未出现的字段按 HIDDEN 处理。

菜单与页面的求交（`09 §3` / `§4`）
-------------------------------
`menus[].page_ids = 菜单关联的 Page ∩ 用户已授权 Page`。
若不求交，前端会拿到指向"无权访问页面"的菜单入口，
进而把"点进去被后端拒绝"当成正常交互 —— 那正是 `09 §3`
明令禁止的"用前端隐藏冒充安全"的镜像错误（这次是把不该显示的显示出来）。

不裁剪空菜单
----------
菜单本身是被授权的资源，是否渲染"没有可访问子页面的菜单"属前端策略。
后端只保证**下发的每一项都是已授权的**，不替前端做渲染决策。

无缓存
-----
`09 §7` / `00 §1#5` 要求权限变更立即生效。本服务**不使用任何缓存**
（Phase 3 裁定：不启用 Redis 权限缓存），每次调用都重新计算 ——
结构上不可能陈旧。缓存与失效机制属 DD-03 / DD-04，留待 Phase 9。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PermissionResourceType
from app.models.permission import PermissionResource
from app.repositories.permission import PermissionResourceRepository
from app.services.effective_permission import EffectivePermissionService, PermissionContext

#: 需要输出到契约的**二元**资源类型（FIELD 走四级策略，单独处理）。
_BINARY_TYPES: tuple[PermissionResourceType, ...] = (
    PermissionResourceType.PAGE,
    PermissionResourceType.MENU,
    PermissionResourceType.BUTTON,
    PermissionResourceType.API,
)


@dataclass(frozen=True, slots=True)
class MenuAccess:
    """一个已授权菜单及其**可访问页面**。"""

    resource: PermissionResource
    page_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PermissionContract:
    """前端权限契约（HTTP 层据此映射为 `PermissionContractResponse`）。"""

    context: PermissionContext
    pages: tuple[PermissionResource, ...]
    menus: tuple[MenuAccess, ...]
    buttons: tuple[PermissionResource, ...]
    apis: tuple[PermissionResource, ...]


def _sort_key(resource: PermissionResource) -> tuple[int, int]:
    """资源定序：`sort_order` 优先，其次 ID。

    与 `PermissionResourceRepository.list_resources` 的排序一致 ——
    前端导航顺序必须与后台配置列表里看到的顺序相同，
    否则"我明明把菜单拖到了第二位"会变成无法解释的差异。
    """
    return (resource.sort_order, resource.id)


class PermissionContractService:
    """构造当前用户的前端动态权限契约（`09 §2`）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._resources = PermissionResourceRepository(session)
        self._effective = EffectivePermissionService(session)

    async def build(self, *, user_id: int) -> PermissionContract:
        """构造权限契约。

        Args:
            user_id: 目标用户（HTTP 层恒为**当前登录者本人**）。

        Raises:
            NotFoundError: 用户不存在或已逻辑删除。
        """
        # `allow_empty_roles=True`：无有效角色是**正常状态**（新账号尚未分配角色），
        # 必须表达成拒绝型上下文而不是 500。详见 DD-21 的处理说明。
        context = await self._effective.build(user_id=user_id, allow_empty_roles=True)

        rows = await self._load_binary_resources(context)
        pages = tuple(sorted(rows[PermissionResourceType.PAGE], key=_sort_key))
        menus = tuple(sorted(rows[PermissionResourceType.MENU], key=_sort_key))
        buttons = tuple(sorted(rows[PermissionResourceType.BUTTON], key=_sort_key))
        apis = tuple(sorted(rows[PermissionResourceType.API], key=_sort_key))

        accessible_page_ids = frozenset(page.id for page in pages)
        menu_page_map = await self._resources.list_menu_page_map([menu.id for menu in menus])
        menu_access = tuple(
            MenuAccess(
                resource=menu,
                page_ids=tuple(
                    sorted(menu_page_map.get(menu.id, frozenset()) & accessible_page_ids)
                ),
            )
            for menu in menus
        )

        return PermissionContract(
            context=context,
            pages=pages,
            menus=menu_access,
            buttons=buttons,
            apis=apis,
        )

    async def _load_binary_resources(
        self, context: PermissionContext
    ) -> dict[PermissionResourceType, list[PermissionResource]]:
        """读取四类二元权限对应的资源行（统一口径：未删除 + ACTIVE）。

        SUPER_ADMIN 与普通用户走**不同来源**但**同一准入口径**：

        | 主体 | 来源 | 理由 |
        |---|---|---|
        | SUPER_ADMIN | 该类型的全部有效资源 | `10 §3` 集中式 bypass 的事实表达 |
        | 其他 | `role_permissions` 授权 ID → 资源行 | 有效权限并集 |

        普通用户路径刻意**多走一次**"按 ID 读资源"：授权表里可能存在
        **已删除或已停用**的授权行（禁用资源不会自动清理历史授权），
        直接信授权行会把已停用资源下发出去。`list_by_ids(only_live=True)`
        是这里唯一的准入闸门。
        """
        if context.is_super_admin:
            return {
                resource_type: await self._resources.list_all_live(resource_type=resource_type)
                for resource_type in _BINARY_TYPES
            }

        granted_by_type = {
            resource_type: context.ids_of(resource_type) for resource_type in _BINARY_TYPES
        }
        all_ids = frozenset().union(*granted_by_type.values()) if granted_by_type else frozenset()
        resources = await self._resources.list_by_ids(sorted(all_ids))

        grouped: dict[PermissionResourceType, list[PermissionResource]] = {
            resource_type: [] for resource_type in _BINARY_TYPES
        }
        for resource in resources:
            bucket = grouped.get(resource.resource_type)
            if bucket is None:
                # FIELD 资源不会出现在授权 ID 集合里（它走四级策略），
                # 走到这里说明数据异常；忽略而不是塞进二元桶。
                continue
            bucket.append(resource)
        return grouped


__all__ = ["MenuAccess", "PermissionContract", "PermissionContractService"]
