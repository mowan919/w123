"""集中式授权入口（Task 2.8）。

Frozen 依据
-----------
Spec `10 §3`：
    SUPER_ADMIN 相关 bypass 必须集中封装。不能让普通管理员通过
    修改请求参数 / 修改 user_id / 修改 session_id / 直接调用 API 绕过保护。
Spec `00 §1#7` / `15 D-007`：其他管理员不能踢 SUPER_ADMIN；仅本人可 logout。
Spec `10 §2`：Authorization 链的最后一环是 Resource ownership / scope。

为什么单独一个模块
----------------
若把 SUPER_ADMIN 判断写在各个 Service 里，会退化成
`if user.is_super_admin:` 到处散落 —— 这正是指令明令禁止的写法。
因此所有"能否操作某用户 / 能否授予某角色"的判断集中在此。

与数据范围的分工
--------------
- **数据范围**（`DataScopeResolver`）决定"看得到谁"；
- **本模块**决定"看得到之后能不能动"，处理范围无法表达的层级保护
  （例如 SUPER_ADMIN 这一层）。
两者是"与"关系，任何一个拒绝都必须整体拒绝。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actor import SUPER_ADMIN_ROLE_CODE, CurrentActor
from app.core.errors import ConflictError, PermissionDeniedError
from app.models.user import AdminUser
from app.repositories.role import RoleRepository
from app.repositories.user import UserRepository


class AuthorizationService:
    """资源级授权判定（集中式）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._roles = RoleRepository(session)
        self._users = UserRepository(session)

    async def is_super_admin_user(self, user_id: int) -> bool:
        """目标用户是否为 SUPER_ADMIN（由角色编码统一推导）。"""
        codes = await self._roles.list_role_codes_for_user(user_id)
        return SUPER_ADMIN_ROLE_CODE in codes

    async def assert_can_manage_user(self, *, actor: CurrentActor, target: AdminUser) -> None:
        """校验操作者是否有权管理目标用户。

        规则（源自 `00 §1#7` + `10 §3`）：
        非 SUPER_ADMIN 不得修改 / 禁用 / 启用 / 删除 / 重置 SUPER_ADMIN 用户的密码。
        """
        if actor.is_super_admin:
            return
        if await self.is_super_admin_user(target.id):
            raise PermissionDeniedError("不能操作 SUPER_ADMIN 用户")

    async def assert_can_assign_roles(
        self, *, actor: CurrentActor, role_ids: frozenset[int]
    ) -> None:
        """校验操作者是否有权授予/撤销这些角色。

        规则（源自 `10 §3` 提权防护）：只有 SUPER_ADMIN 可以授予或撤销
        SUPER_ADMIN 角色。
        """
        if not role_ids:
            return
        roles = await self._roles.list_by_ids(sorted(role_ids))
        codes = {role.role_code for role in roles}
        if SUPER_ADMIN_ROLE_CODE in codes and not actor.is_super_admin:
            raise PermissionDeniedError("只有 SUPER_ADMIN 可以授予 SUPER_ADMIN 角色")

    async def assert_not_last_super_admin(self, *, target: AdminUser) -> None:
        """阻止把系统中最后一个 SUPER_ADMIN 禁用或删除。

        INTERIM 约束：Spec `00 §1#7` 只规定"其他管理员不能踢 SUPER_ADMIN"，
        未直接规定"不能删除最后一个 SUPER_ADMIN"。此处按该条冻结规则的
        **意图**（系统必须始终存在可管理主体）做保护，已登记待确认。
        """
        if not await self.is_super_admin_user(target.id):
            return
        remaining = await self._users.count_super_admins()
        if remaining <= 1:
            raise ConflictError("系统必须保留至少一个未删除的 SUPER_ADMIN 用户")


__all__ = ["AuthorizationService"]
