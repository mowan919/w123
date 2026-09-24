"""数据范围解析与授权入口（Task 2.7 / Task 2.8 的核心；Phase 3 扩展多角色合并）。

Frozen 依据
-----------
- Spec `03 §10`：ALL / DEPARTMENT / DEPARTMENT_CHILDREN / SELF / CUSTOM；
  部门管理员默认 `DEPARTMENT_CHILDREN`。
- Spec `00 §1#1` / `15 D-001`：部门管理员 = 本部门 + 所有子部门。
- Spec `00 §1#2` / `15 D-002`：多角色权限**取并集**。
- Spec `10 §3`：SUPER_ADMIN 的 bypass 必须集中封装。
- Spec `11 §5` 取向：宁可拒绝，也不放行。
- **DD-19 已冻结**：多角色数据范围按**可见集合求并（最宽）**合并。

集中的三件事（避免散落各处）
--------------------------
1. **SUPER_ADMIN 判定** → 唯一入口 `CurrentActor.is_super_admin`；
2. **策略 → 查询约束的解析** → 本模块 `DataScopeResolver.resolve`；
3. **资源是否在范围内** → `ResolvedScope.allows_department` / `allows_user`
   / `user_scope_condition`。

因此业务 Service 中**不出现** `if actor.is_super_admin:` 的分支，
只调用 `resolve()` 后使用结果。

多角色合并（Phase 3 新增）
-----------------------
`resolve()` 逐角色解析（`CurrentActor.effective_role_scopes()`），
再用 `ResolvedScope.merge` 求并。单角色场景下合并结果与 Phase 2 逐字段等价，
因此本次改动**不改变**既有单角色行为；只有真正的多角色用户才会得到
"部门集合求并 + 可能额外包含本人"的结果（DD-19 冻结语义）。

fail-closed 行为
---------------
- 未分配部门的 DEPARTMENT / DEPARTMENT_CHILDREN → 空集合（什么都看不到）；
- CUSTOM 未配置 → 空集合；
- SELF → 部门维度为空集合，用户维度严格限定为本人；
- 任何"解析不出具体集合"的情形都收敛为**拒绝**，绝不退化为 ALL；
- 合并输入为空（无角色）→ 抛错而非静默放行。
"""

from __future__ import annotations

import logging

from app.auth.actor import CurrentActor
from app.core.scope import DataScope, ResolvedScope, RoleScopeConfig
from app.repositories.department import DepartmentRepository

logger = logging.getLogger(__name__)


class DataScopeResolver:
    """把 `CurrentActor` 解析为可下推 SQL 的 `ResolvedScope`。"""

    def __init__(self, department_repository: DepartmentRepository) -> None:
        self._departments = department_repository

    async def resolve(self, actor: CurrentActor) -> ResolvedScope:
        """解析操作者的**有效**数据范围（多角色求并，DD-19）。

        SUPER_ADMIN 直接得到全局范围：这是 Spec `00 §1#7` / `10 §3`
        要求的集中式 bypass，不参与角色合并计算。
        """
        return await self.resolve_for_subject(
            user_id=actor.user_id,
            department_id=actor.department_id,
            is_super_admin=actor.is_super_admin,
            configs=actor.effective_role_scopes(),
        )

    async def resolve_for_roles(
        self,
        actor: CurrentActor,
        configs: tuple[RoleScopeConfig, ...],
    ) -> ResolvedScope:
        """按**显式给定**的角色配置解析（认证层已把角色范围读出来时使用）。

        为什么提供这个入口：认证层（Phase 4）在一次请求里已经查过用户的
        角色与其 CUSTOM 部门集合，再让本模块重新查一遍是浪费；
        同时它也让"角色范围来源"完全可控，避免隐式回落。
        """
        return await self.resolve_for_subject(
            user_id=actor.user_id,
            department_id=actor.department_id,
            is_super_admin=actor.is_super_admin,
            configs=configs,
        )

    async def resolve_for_subject(
        self,
        *,
        user_id: int,
        department_id: int | None,
        is_super_admin: bool,
        configs: tuple[RoleScopeConfig, ...],
    ) -> ResolvedScope:
        """以**原始主体参数**解析数据范围。

        之所以不直接接受 `CurrentActor`：权限预览（`03 §11`）要计算的是
        **被预览用户**的范围，而不是操作者的范围 —— 此时不存在一个
        "被预览用户的 CurrentActor"。用原始参数可以让两条路径复用同一实现，
        避免"操作者走一套、被预览者走另一套"的双份真相。
        """
        if is_super_admin:
            return ResolvedScope.global_scope(actor_id=user_id)
        if not configs:
            # 无角色 = 无任何范围来源。fail-closed：抛错而不是放行。
            raise ValueError("fail-closed：无任何角色范围配置，无法解析数据范围。")

        resolved = [
            await self._resolve_role_scope(user_id, department_id, config) for config in configs
        ]
        return ResolvedScope.merge(resolved, actor_id=user_id)

    async def _resolve_role_scope(
        self,
        user_id: int,
        department_id: int | None,
        config: RoleScopeConfig,
    ) -> ResolvedScope:
        """把**单个角色**的范围配置解析为 `ResolvedScope`。"""
        match config.data_scope:
            case DataScope.ALL:
                # Spec 03 §10 允许角色配置 ALL。此处放行但留痕，
                # 便于发现"误配导致普通管理员获得全局范围"。
                logger.warning(
                    "non_super_admin_with_global_scope user_id=%s department_id=%s role_id=%s",
                    user_id,
                    department_id,
                    config.role_id,
                )
                return ResolvedScope.global_scope(actor_id=user_id)

            case DataScope.DEPARTMENT:
                ids = frozenset({department_id}) if department_id is not None else frozenset()
                return ResolvedScope.for_departments(
                    ids, scope=DataScope.DEPARTMENT, actor_id=user_id
                )

            case DataScope.DEPARTMENT_CHILDREN:
                # 冻结语义：本部门 + 所有子部门（含自身）
                if department_id is None:
                    ids = frozenset()
                else:
                    ids = await self._departments.descendant_ids(department_id, include_self=True)
                return ResolvedScope.for_departments(
                    ids, scope=DataScope.DEPARTMENT_CHILDREN, actor_id=user_id
                )

            case DataScope.SELF:
                # 部门维度为空集合：不预先授予任何部门可见性（fail-closed）。
                return ResolvedScope.self_only(actor_id=user_id)

            case DataScope.CUSTOM:
                # DD-07 已冻结 CUSTOM 的存储模型；此处消费认证层注入的集合，
                # 未配置（None / 空）一律按空集合处理 → 什么都看不到。
                return ResolvedScope.for_departments(
                    config.custom_department_ids,
                    scope=DataScope.CUSTOM,
                    actor_id=user_id,
                )

        # 不可达：DataScope 为闭合枚举。防御性 fail-closed。
        raise ValueError(f"未知数据范围策略：{config.data_scope!r}")

    async def scope_department_ids(self, actor: CurrentActor) -> frozenset[int] | None:
        """返回范围内的部门 ID 集合；None 表示不限制（仅 SUPER_ADMIN / ALL）。"""
        return (await self.resolve(actor)).department_ids


__all__ = ["DataScopeResolver"]
