"""有效权限引擎（Task 3.11：`AuthorizationService` → `PermissionContext`）。

Frozen / 已裁定依据
------------------
- Spec `00 §1#2` / `15 D-002`：用户可持有多个角色，有效权限 = **并集**。
- Spec `00 §1#3` / `15 D-003` / `03 §4`：角色继承 V1 支持，继承权限必须计入。
- Spec `00 §1#5` / `15 D-005` / `03 §12` / `09 §7`：权限变更**立即生效**。
- Spec `03 §9` / `00 §3`：字段权限四级，最终策略由后端统一计算并输出。
- Spec `09 §2`：`/auth/permissions` 需返回 pages / menus / buttons / APIs /
  fields / data scopes / permission version。
- Spec `03 §11`：建议提供权限预览（来源角色 / 继承链 / Field 权限）。
- Spec `10 §10`：约束必须下推 SQL。
- Spec `11 §5`：缓存错误不得导致权限放大 —— 因此本引擎**不做任何缓存**，
  每次按请求实时计算（Phase 3 人类裁定：不启用 Redis 权限缓存）。
- **DD-19 / DD-05 / DD-06 已冻结**：范围求并、继承展开、字段等级最宽松者胜。

为什么"每个请求重算"而不是缓存
----------------------------
Spec `00 §1#5` 冻结"权限变更立即生效"，`11 §5` 又要求"宁可短暂 cache miss，
也不能用过期权限放行"。Phase 3 的裁定是：**不引入缓存**，
用"实时计算"换取"结构上不可能陈旧"。缓存与失效机制（DD-03 / DD-04）
留到 Phase 9 再加，届时本引擎即可直接作为回源实现。

禁用角色不授予权限（关键安全点）
---------------------------
`roles.status = DISABLED` 的角色**不参与并集**。若只按 `deleted_at` 过滤，
"禁用角色"这个动作就会变成纯装饰 —— 权限照旧生效。因此：
1. 直接角色先筛 ACTIVE；
2. 继承展开出来的祖先角色**再筛一次** ACTIVE（祖先可能是被禁用的）。

第二步极易漏掉：若只在展开前过滤一次，展开出的禁用祖先会带权限进来。

已登记的 RISK（不在本 Phase 自行修改）
-----------------------------------
**RISK-004**：`is_super_admin` 的判定沿用既有集中式口径
（`AuthorizationService.is_super_admin_user`，只按"角色未删除"判断，
不筛 `status`），而权限并集口径会筛 ACTIVE。两者口径不同，
极端情况下"持有被禁用的 SUPER_ADMIN 角色"仍会被当作 SUPER_ADMIN。
该行为**不在本 Phase 自行更改**（属于已冻结的集中式规则的语义变更），
已登记 RISK-004 待人类冻结。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actor import SUPER_ADMIN_ROLE_CODE
from app.core.errors import NotFoundError
from app.core.scope import DataScope, ResolvedScope, RoleScopeConfig
from app.models.enums import (
    FieldAccessLevel,
    PermissionResourceType,
    most_permissive_field_level,
)
from app.repositories.department import DepartmentRepository
from app.repositories.permission import (
    PermissionResourceRepository,
    PermissionVersionRepository,
    RoleInheritanceRepository,
    RolePermissionRepository,
)
from app.repositories.role import RoleRepository
from app.repositories.user import UserRepository
from app.services.data_scope import DataScopeResolver

logger = logging.getLogger(__name__)

#: 角色继承展开的深度上限（DD-05 冻结：超限 fail-closed）。
#:
#: 取 32 的理由：正常组织结构不可能达到该深度，而一旦达到就基本可以断定
#: 库里存在环（`UNION` 会让环收敛，但收敛结果无业务意义）。
#: 超限抛 `RoleInheritanceDepthExceededError`（5xx + 告警），
#: 而不是静默接受一个可疑的权限集合。
MAX_ROLE_INHERITANCE_DEPTH = 32


@dataclass(frozen=True, slots=True)
class FieldPermissionPolicy:
    """单个字段的有效权限策略。"""

    field_id: int
    field_key: str
    owner_resource_id: int | None
    resource_code: str
    access_level: FieldAccessLevel


@dataclass(frozen=True, slots=True)
class PermissionContext:
    """当前用户的**有效权限上下文**（Spec `09 §2` 的落地载体）。

    Attributes:
        user_id: 用户 ID。
        direct_role_ids: 直接持有的 ACTIVE 角色。
        inherited_role_ids: 通过继承获得（不含直接角色）的 ACTIVE 角色。
        resource_ids: `resource_type → 授权资源 ID 集合`（四类二元权限）。
        resource_codes: `resource_type → 授权资源编码集合`。
        field_policies: 有效字段策略（已按"最宽松者胜"合并）。
        data_scope: 有效数据范围（DD-19 求并结果）。
        version: 权限版本号（`permission_versions`，DD-04 未冻结其缓存语义）。
        is_super_admin: 是否为 SUPER_ADMIN（集中式判定口径）。
    """

    user_id: int
    direct_role_ids: frozenset[int] = field(default_factory=frozenset)
    inherited_role_ids: frozenset[int] = field(default_factory=frozenset)
    resource_ids: dict[PermissionResourceType, frozenset[int]] = field(default_factory=dict)
    resource_codes: dict[PermissionResourceType, frozenset[str]] = field(default_factory=dict)
    field_policies: tuple[FieldPermissionPolicy, ...] = ()
    data_scope: ResolvedScope | None = None
    version: int = 0
    is_super_admin: bool = False

    # ------------------------------------------------------------------
    # 便捷判定
    # ------------------------------------------------------------------
    @property
    def effective_role_ids(self) -> frozenset[int]:
        """有效角色集合 = 直接角色 ∪ 继承角色。"""
        return self.direct_role_ids | self.inherited_role_ids

    def ids_of(self, resource_type: PermissionResourceType) -> frozenset[int]:
        """某类权限的授权资源 ID 集合。"""
        return self.resource_ids.get(resource_type, frozenset())

    def codes_of(self, resource_type: PermissionResourceType) -> frozenset[str]:
        """某类权限的授权资源编码集合。"""
        return self.resource_codes.get(resource_type, frozenset())

    @property
    def page_ids(self) -> frozenset[int]:
        return self.ids_of(PermissionResourceType.PAGE)

    @property
    def menu_ids(self) -> frozenset[int]:
        return self.ids_of(PermissionResourceType.MENU)

    @property
    def button_ids(self) -> frozenset[int]:
        return self.ids_of(PermissionResourceType.BUTTON)

    @property
    def api_ids(self) -> frozenset[int]:
        return self.ids_of(PermissionResourceType.API)

    @property
    def api_codes(self) -> frozenset[str]:
        return self.codes_of(PermissionResourceType.API)

    def has_api_permission(self, api_code: str) -> bool:
        """是否拥有某个 API 权限（后端强制授权的判定入口）。

        SUPER_ADMIN 直接放行 —— 这是 Spec `10 §3` 要求的**集中式 bypass**，
        只在此处出现一次，业务代码中不得再写 `if actor.is_super_admin`。
        """
        if self.is_super_admin:
            return True
        return api_code in self.api_codes

    def field_policy_map(self) -> dict[str, FieldAccessLevel]:
        """字段名 → 有效等级（供 Phase 8 输出字段策略）。"""
        return {policy.field_key: policy.access_level for policy in self.field_policies}


@dataclass(frozen=True, slots=True)
class PermissionPreview:
    """权限预览（Spec `03 §11` 建议能力）。

    Attributes:
        context: 有效权限上下文。
        role_summaries: 有效角色的摘要（id / code / name / 是否直接持有）。
        inheritance_edges: 参与继承链的 (parent_role_id, child_role_id) 边。
    """

    context: PermissionContext
    role_summaries: tuple[tuple[int, str, str, bool], ...]
    inheritance_edges: frozenset[tuple[int, int]]


class EffectivePermissionService:
    """有效权限计算（多角色并集 + 继承展开 + 字段等级合并 + 范围求并）。"""

    def __init__(
        self,
        session: AsyncSession,
        *,
        max_inheritance_depth: int = MAX_ROLE_INHERITANCE_DEPTH,
    ) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._roles = RoleRepository(session)
        self._permissions = RolePermissionRepository(session)
        self._resources = PermissionResourceRepository(session)
        self._inheritances = RoleInheritanceRepository(session)
        self._versions = PermissionVersionRepository(session)
        self._data_scope = DataScopeResolver(DepartmentRepository(session))
        self._max_depth = max_inheritance_depth

    # ------------------------------------------------------------------
    # 计算
    # ------------------------------------------------------------------
    async def build(self, *, user_id: int) -> PermissionContext:
        """计算用户的有效权限上下文。

        Raises:
            NotFoundError: 用户不存在或已逻辑删除。
        """
        user = await self._users.get(user_id)
        if user is None:
            raise NotFoundError("用户不存在")

        # 1. 直接角色（未删除 + ACTIVE）
        direct_role_ids = await self._roles.list_active_role_ids_for_user(user_id)

        # 2. 继承展开 → 祖先角色集合
        raw_effective: frozenset[int] = frozenset()
        if direct_role_ids:
            raw_effective = await self._inheritances.expand_role_ids(
                sorted(direct_role_ids), max_depth=self._max_depth
            )

        # 3. 祖先角色**再筛一次** ACTIVE：展开出来的祖先可能是被禁用的，
        #    只靠第 1 步的过滤无法覆盖它们（见模块说明）。
        effective_role_ids = await self._inheritances.list_active_role_ids(sorted(raw_effective))

        inherited_role_ids = effective_role_ids - direct_role_ids

        # 4. 四类二元权限取并集
        resource_ids: dict[PermissionResourceType, frozenset[int]] = {}
        for resource_type in (
            PermissionResourceType.PAGE,
            PermissionResourceType.MENU,
            PermissionResourceType.BUTTON,
            PermissionResourceType.API,
        ):
            resource_ids[resource_type] = await self._permissions.list_resource_ids_for_roles(
                sorted(effective_role_ids), resource_type
            )

        # 5. 资源编码（供前端与 API 判权直接使用，避免再查一次资源表）
        all_resource_ids = (
            frozenset().union(*resource_ids.values()) if resource_ids else frozenset()
        )
        resources = await self._resources.list_by_ids(sorted(all_resource_ids))
        codes_by_type: dict[PermissionResourceType, set[str]] = defaultdict(set)
        for resource in resources:
            codes_by_type[resource.resource_type].add(resource.resource_code)

        # 6. 字段权限：多角色等级按"最宽松者胜"合并（DD-06 冻结）
        raw_field_levels = await self._permissions.list_field_levels_for_roles(
            sorted(effective_role_ids)
        )
        grouped: dict[int, list[FieldAccessLevel]] = defaultdict(list)
        for field_id, level in raw_field_levels:
            grouped[field_id].append(level)

        field_policies = await self._build_field_policies(grouped)

        # 7. 数据范围：逐角色配置 → 求并（DD-19 冻结）
        configs = await self._build_scope_configs(effective_role_ids)
        role_codes = await self._roles.list_role_codes_for_user(user_id)
        is_super_admin = SUPER_ADMIN_ROLE_CODE in role_codes
        data_scope = await self._data_scope.resolve_for_subject(
            user_id=user.id,
            department_id=user.department_id,
            is_super_admin=is_super_admin,
            configs=configs,
        )

        return PermissionContext(
            user_id=user.id,
            direct_role_ids=direct_role_ids,
            inherited_role_ids=inherited_role_ids,
            resource_ids=resource_ids,
            resource_codes={
                resource_type: frozenset(codes_by_type.get(resource_type, set()))
                for resource_type in PermissionResourceType
                if codes_by_type.get(resource_type)
            },
            field_policies=field_policies,
            data_scope=data_scope,
            version=await self._versions.get(),
            is_super_admin=is_super_admin,
        )

    async def resolve_api_codes(self, user_id: int) -> frozenset[str]:
        """**轻量路径**：只解析有效 API 权限编码。

        为什么需要单独一条路径：`assert_api_permission` 是每个受保护请求
        都会走的热路径（Spec `08 §10`），而 `build()` 还会解析数据范围、
        字段等级、版本号、资源编码映射 —— 对判权而言是浪费。
        本方法只做"角色 → 继承 → API 授权 → 编码"这一条最小链路。

        与 `build()` 共享同一套过滤口径（ACTIVE 角色、有效资源），
        因此不会出现"轻量路径放行、完整路径拒绝"的分歧。
        """
        direct_role_ids = await self._roles.list_active_role_ids_for_user(user_id)
        if not direct_role_ids:
            return frozenset()

        raw_effective = await self._inheritances.expand_role_ids(
            sorted(direct_role_ids), max_depth=self._max_depth
        )
        effective_role_ids = await self._inheritances.list_active_role_ids(sorted(raw_effective))
        if not effective_role_ids:
            return frozenset()

        api_resource_ids = await self._permissions.list_resource_ids_for_roles(
            sorted(effective_role_ids), PermissionResourceType.API
        )
        if not api_resource_ids:
            return frozenset()

        resources = await self._resources.list_by_ids(sorted(api_resource_ids))
        return frozenset(resource.resource_code for resource in resources)

    async def _build_field_policies(
        self, grouped: dict[int, list[FieldAccessLevel]]
    ) -> tuple[FieldPermissionPolicy, ...]:
        """把"字段 ID → 等级列表"整理为已合并的策略元组。"""
        if not grouped:
            return ()
        fields = await self._resources.list_by_ids(sorted(grouped))
        policies: list[FieldPermissionPolicy] = []
        for field_resource in fields:
            merged = most_permissive_field_level(grouped[field_resource.id])
            if merged is None:  # pragma: no cover - grouped 的键即字段 ID，必非空
                continue
            policies.append(
                FieldPermissionPolicy(
                    field_id=field_resource.id,
                    field_key=field_resource.field_key or field_resource.resource_code,
                    owner_resource_id=field_resource.owner_resource_id,
                    resource_code=field_resource.resource_code,
                    access_level=merged,
                )
            )
        policies.sort(key=lambda policy: policy.field_id)
        return tuple(policies)

    async def _build_scope_configs(
        self, effective_role_ids: frozenset[int]
    ) -> tuple[RoleScopeConfig, ...]:
        """构造逐角色的数据范围配置（DD-19 求并输入）。

        非 CUSTOM 角色即使库中存在残留的 CUSTOM 关联行也不消费它们：
        按语义那些行**本就应该被清空**（`RoleDataScopeService` 的责任），
        忽略它们得到的是该角色**自身配置**的范围，既不放宽也不缩小。
        出现残留说明上游写入路径有 bug，因此记 warning（数据完整性告警）。
        """
        if not effective_role_ids:
            return ()
        roles = await self._roles.list_by_ids(sorted(effective_role_ids))
        custom_map = await self._roles.list_custom_scope_departments_for_roles(
            sorted(effective_role_ids)
        )
        configs: list[RoleScopeConfig] = []
        for role in roles:
            is_custom = role.data_scope is DataScope.CUSTOM
            if not is_custom and custom_map.get(role.id):
                logger.warning(
                    "custom_scope_residue role_id=%s data_scope=%s rows=%s",
                    role.id,
                    role.data_scope.value,
                    len(custom_map[role.id]),
                )
            configs.append(
                RoleScopeConfig(
                    role_id=role.id,
                    data_scope=role.data_scope,
                    custom_department_ids=custom_map.get(role.id, frozenset())
                    if is_custom
                    else frozenset(),
                )
            )
        return tuple(configs)

    # ------------------------------------------------------------------
    # 预览
    # ------------------------------------------------------------------
    async def preview(self, *, user_id: int) -> PermissionPreview:
        """权限预览（Spec `03 §11`）：有效权限 + 来源角色 + 继承链。"""
        context = await self.build(user_id=user_id)
        roles = await self._roles.list_by_ids(sorted(context.effective_role_ids))
        summaries = tuple(
            (
                role.id,
                role.role_code,
                role.role_name,
                role.id in context.direct_role_ids,
            )
            for role in sorted(roles, key=lambda item: item.id)
        )
        edges = await self._inheritances.list_relations_for_roles(
            sorted(context.effective_role_ids)
        )
        return PermissionPreview(
            context=context,
            role_summaries=summaries,
            inheritance_edges=edges,
        )


__all__ = [
    "MAX_ROLE_INHERITANCE_DEPTH",
    "EffectivePermissionService",
    "FieldPermissionPolicy",
    "PermissionContext",
    "PermissionPreview",
]
