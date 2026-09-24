"""数据范围解析与授权入口（Task 2.7 / Task 2.8 的核心）。

Frozen 依据
-----------
- Spec `03 §10`：ALL / DEPARTMENT / DEPARTMENT_CHILDREN / SELF / CUSTOM；
  部门管理员默认 `DEPARTMENT_CHILDREN`。
- Spec `00 §1#1` / `15 D-001`：部门管理员 = 本部门 + 所有子部门。
- Spec `10 §3`：SUPER_ADMIN 的 bypass 必须集中封装。
- Spec `11 §5` 取向：宁可拒绝，也不放行。

集中的三件事（避免散落各处）
--------------------------
1. **SUPER_ADMIN 判定** → 唯一入口 `CurrentActor.is_super_admin`；
2. **策略 → 查询约束的解析** → 本模块 `DataScopeResolver.resolve`；
3. **资源是否在范围内** → `ResolvedScope.allows_department` / `user_scope_condition`。

因此业务 Service 中**不出现** `if actor.is_super_admin:` 的分支，
只调用 `resolve()` 后使用结果。

fail-closed 行为
---------------
- 未分配部门的 DEPARTMENT / DEPARTMENT_CHILDREN → 空集合（什么都看不到）；
- CUSTOM 未配置（DD-07 存储未冻结）→ 空集合；
- SELF → 部门维度为空集合，用户维度严格限定为本人；
- 任何"解析不出具体集合"的情形都收敛为**拒绝**，绝不退化为 ALL。
"""

from __future__ import annotations

import logging

from app.auth.actor import CurrentActor
from app.core.scope import DataScope, ResolvedScope
from app.repositories.department import DepartmentRepository

logger = logging.getLogger(__name__)


class DataScopeResolver:
    """把 `CurrentActor` 解析为可下推 SQL 的 `ResolvedScope`。"""

    def __init__(self, department_repository: DepartmentRepository) -> None:
        self._departments = department_repository

    async def resolve(self, actor: CurrentActor) -> ResolvedScope:
        """解析操作者的数据范围。"""
        if actor.is_super_admin:
            # SUPER_ADMIN 全局范围（Spec 00 §1 / 10 §3）
            return ResolvedScope.global_scope(actor_id=actor.user_id)

        match actor.data_scope:
            case DataScope.ALL:
                # Spec 03 §10 允许角色配置 ALL。此处放行但留痕，
                # 便于发现"误配导致普通管理员获得全局范围"。
                logger.warning(
                    "non_super_admin_with_global_scope user_id=%s username=%s",
                    actor.user_id,
                    actor.username,
                )
                return ResolvedScope.global_scope(actor_id=actor.user_id)

            case DataScope.DEPARTMENT:
                ids = (
                    frozenset({actor.department_id})
                    if actor.department_id is not None
                    else frozenset()
                )
                return ResolvedScope.for_departments(
                    ids, scope=DataScope.DEPARTMENT, actor_id=actor.user_id
                )

            case DataScope.DEPARTMENT_CHILDREN:
                # 冻结语义：本部门 + 所有子部门（含自身）
                if actor.department_id is None:
                    ids = frozenset()
                else:
                    ids = await self._departments.descendant_ids(
                        actor.department_id, include_self=True
                    )
                return ResolvedScope.for_departments(
                    ids, scope=DataScope.DEPARTMENT_CHILDREN, actor_id=actor.user_id
                )

            case DataScope.SELF:
                # 部门维度为空集合：不预先授予任何部门可见性（fail-closed）。
                return ResolvedScope.self_only(actor_id=actor.user_id)

            case DataScope.CUSTOM:
                # DD-07（CUSTOM 存储模型）未冻结：只接受外部传入的集合，
                # 未配置时按空集合处理。
                ids = actor.custom_department_ids or frozenset()
                return ResolvedScope.for_departments(
                    ids, scope=DataScope.CUSTOM, actor_id=actor.user_id
                )

        # 不可达：DataScope 为闭合枚举。防御性 fail-closed。
        raise ValueError(f"未知数据范围策略：{actor.data_scope!r}")

    async def scope_department_ids(self, actor: CurrentActor) -> frozenset[int] | None:
        """返回范围内的部门 ID 集合；None 表示不限制（仅 SUPER_ADMIN / ALL）。"""
        return (await self.resolve(actor)).department_ids


__all__ = ["DataScopeResolver"]
