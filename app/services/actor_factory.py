"""把已认证的用户装配为 `CurrentActor`（Phase 4）。

为什么单独一个模块
----------------
`CurrentActor` 是**认证结果**，而它的三个关键成分（角色编码、逐角色数据范围配置、
所属部门）都来自数据库。装配逻辑一旦散落到依赖函数、服务与测试里，
就会出现"某条路径忘了带 `role_scopes`"的漂移 ——
后果是数据范围静默退化为 fail-closed 的 SELF（功能异常）
或反之被放宽（安全事故）。因此收敛为单一入口。

与 `EffectivePermissionService` 的分工
------------------------------------
| 关注点 | 归属 |
|---|---|
| **我是谁**（身份 + 角色 + 范围**配置**） | 本模块（一次请求一次） |
| **我能做什么**（权限并集、继承展开、字段等级、范围**解析**） | `EffectivePermissionService` |
| 范围**解析**（`DataScope` 合并 / 访问判定） | `DataScopeResolver` |

本模块**从不**判断权限，只负责把"已经落库的事实"搬进 `CurrentActor`。
因此在这里不会出现任何 `if actor.is_super_admin` 之类的分支。

RISK-004 的一致性选择
-------------------
`role_codes` 走 `RoleRepository.list_role_codes_for_user`（只筛 `deleted_at`），
与 `AuthorizationService` 的集中式 SUPER_ADMIN 判定**完全同源**。
明知它与"权限并集筛 ACTIVE"的口径不一致（RISK-004），仍然同源的理由：
若这里自行改成筛 ACTIVE，就会出现"认证层认为不是超管、授权层认为是超管"
的**更严重**分歧 —— 那会把一个已登记的风险升级为不一致的实现。
口径统一由人类裁定后再一次性修正（RISK-004 已登记）。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actor import CurrentActor
from app.core.scope import DataScope, RoleScopeConfig, widest_data_scope
from app.models.user import AdminUser
from app.repositories.role import RoleRepository
from app.repositories.user import UserRepository


class ActorFactory:
    """从用户记录装配 `CurrentActor`。"""

    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._roles = RoleRepository(session)

    async def build(
        self,
        user: AdminUser,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> CurrentActor:
        """用**已加载**的用户装配操作者（认证层已持有用户对象时使用）。"""
        role_codes = await self._roles.list_role_codes_for_user(user.id)
        role_scopes = await self.build_role_scopes(user.id)

        return CurrentActor(
            user_id=user.id,
            username=user.username,
            role_codes=role_codes,
            # `data_scope` 只是 `role_scopes` 为空时的**回落值**。
            # 无角色时回落为 SELF（fail-closed：什么都看不到），
            # 绝不回落为 ALL。
            data_scope=(
                widest_data_scope([config.data_scope for config in role_scopes])
                if role_scopes
                else DataScope.SELF
            ),
            department_id=user.department_id,
            # CUSTOM 部门集合已逐角色放进 `role_scopes`，
            # 因此不再使用单一 `custom_department_ids`（避免两处真相）。
            custom_department_ids=None,
            role_scopes=role_scopes,
            ip=ip,
            user_agent=user_agent,
        )

    async def build_role_scopes(self, user_id: int) -> tuple[RoleScopeConfig, ...]:
        """读取用户的**逐角色**数据范围配置（DD-19 合并输入）。

        只取**未删除且 ACTIVE** 的角色：被禁用的角色必须立刻失去其范围
        （否则"禁用角色"只影响权限、不影响数据范围，等于半失效）。

        非 CUSTOM 角色即使库中存在残留的 CUSTOM 关联行也不携带它们，
        与 `EffectivePermissionService._build_scope_configs` 保持同一口径
        （残留行说明上游写入有 bug，忽略它得到的是该角色自身配置的范围，
        既不放宽也不缩小）。
        """
        active_role_ids = await self._roles.list_active_role_ids_for_user(user_id)
        if not active_role_ids:
            return ()

        roles = await self._roles.list_by_ids(sorted(active_role_ids))
        custom_map = await self._roles.list_custom_scope_departments_for_roles(
            sorted(active_role_ids)
        )

        configs: list[RoleScopeConfig] = []
        for role in sorted(roles, key=lambda item: item.id):
            is_custom = role.data_scope is DataScope.CUSTOM
            configs.append(
                RoleScopeConfig(
                    role_id=role.id,
                    data_scope=role.data_scope,
                    custom_department_ids=(
                        custom_map.get(role.id, frozenset()) if is_custom else frozenset()
                    ),
                )
            )
        return tuple(configs)

    async def build_for_user_id(
        self,
        user_id: int,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> CurrentActor | None:
        """按用户 ID 装配操作者；用户不存在或已逻辑删除时返回 None。

        Returns:
            `CurrentActor`，或 None。**不抛异常** ——
            调用方（认证依赖）需要把"查不到"表达为统一的 401，
            而不是让异常类型泄漏"该用户是否存在"。
        """
        user = await self._users.get(user_id)
        if user is None:
            return None
        return await self.build(user, ip=ip, user_agent=user_agent)


__all__ = ["ActorFactory"]
