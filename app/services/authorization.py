"""集中式授权入口（Task 2.8 建立；Task 3.11 接入 API Permission）。

Frozen 依据
-----------
Spec `10 §2` Authorization：
    Authentication → Role → Permission → API Permission → Data Scope
    → Resource ownership / scope。
Spec `10 §3`：
    SUPER_ADMIN 相关 bypass 必须集中封装。不能让普通管理员通过
    修改请求参数 / 修改 user_id / 修改 session_id / 直接调用 API 绕过保护。
Spec `00 §1#7` / `15 D-007`：其他管理员不能踢 SUPER_ADMIN；仅本人可 logout。
Spec `08 §10`：每个受保护 API 必须经过后端 API Permission 校验。
Spec `03 §8`：API Permission 是后端强制授权，不能只依赖前端按钮隐藏。

为什么单独一个模块
----------------
若把 SUPER_ADMIN 判断写在各个 Service 里，会退化成
`if user.is_super_admin:` 到处散落 —— 这正是指令明令禁止的写法。
因此所有"能否操作某用户 / 能否管理角色 / 能否调用某 API"的判断集中在此。

与数据范围的分工
--------------
- **数据范围**（`DataScopeResolver`）决定"看得到谁"；
- **本模块**决定"看得到之后能不能动"，处理范围无法表达的层级保护
  （例如 SUPER_ADMIN 这一层）。
两者是"与"关系，任何一个拒绝都必须整体拒绝。

Phase 3 变更：INTERIM 授权被真实的 API Permission 取代
---------------------------------------------------
Phase 2 时 `assert_can_manage_roles` 是 **INTERIM 保守默认**（仅 SUPER_ADMIN），
因为当时权限资源定义入口缺失（CONFLICT-001），没有可依据的权限位。
DD-20 冻结后资源模型落地，该方法改为**基于 API Permission 判定**：

- SUPER_ADMIN → 集中式 bypass（Spec `10 §3`，只在此处出现一次）；
- 其他用户 → 必须在其**有效 API 权限集合**（含继承）中具备该 API code。

fail-closed 细节：查不到用户（已删除 / ID 伪造）时**不放行**，
而不是抛 404 —— 授权层不应向外暴露"该用户是否存在"。

已登记的 RISK（不在本 Phase 自行修改）
-----------------------------------
**RISK-004**：`actor.is_super_admin`（token 派生的 `role_codes`）与
`is_super_admin_user`（DB 角色）都不筛 `roles.status`，
而有效权限并集**会**筛 ACTIVE。口径差异意味着
"持有被禁用的 SUPER_ADMIN 角色"仍会被当作 SUPER_ADMIN。
这属于已冻结集中式规则的语义变更，不在本 Phase 自行更改，已登记待冻结。
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.actor import SUPER_ADMIN_ROLE_CODE, CurrentActor
from app.core.errors import ConflictError, PermissionDeniedError
from app.models.user import AdminUser
from app.repositories.role import RoleRepository
from app.repositories.user import UserRepository
from app.services.effective_permission import EffectivePermissionService


class ApiPermissionCode(StrEnum):
    """代码中引用的 API 权限编码。

    INTERIM：`resource_code` 的字面量命名规范（大小写、分隔符、前缀）
    Spec 未冻结。此处集中定义，Phase 9 冻结后只改这一处；
    同时这些编码也是 Phase 8 声明式绑定（`require_api_permission`）的入参。

    为什么用枚举而不是散落字符串：`resource_code` 一旦拼错，
    表现是"永远 403"（可用性事故）或"永远放行"（安全事故），
    两者都不容易在测试里发现，集中定义可以把拼错压缩到一处。
    """

    #: 管理角色：角色 CRUD、数据范围、权限授予、继承关系。
    ROLE_MANAGE = "ROLE_MANAGE"
    #: 管理权限资源定义（Page / Menu / Button / API / Field）。
    PERMISSION_RESOURCE_MANAGE = "PERMISSION_RESOURCE_MANAGE"
    #: 查看权限预览（`03 §11`）。
    PERMISSION_PREVIEW = "PERMISSION_PREVIEW"


class AuthorizationService:
    """资源级授权判定（集中式）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._roles = RoleRepository(session)
        self._users = UserRepository(session)
        self._effective_permissions = EffectivePermissionService(session)

    # ------------------------------------------------------------------
    # 用户层级保护
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # API Permission（Task 3.11：取代 Phase 2 的 INTERIM 保守默认）
    # ------------------------------------------------------------------
    async def has_api_permission(self, *, actor: CurrentActor, api_code: str) -> bool:
        """操作者是否具备某个 API 权限（不抛异常版本，供"多权限任一"等场景）。"""
        if actor.is_super_admin:
            return True
        user = await self._users.get(actor.user_id)
        if user is None:
            # fail-closed：身份无法确认时按无权限处理。
            return False
        codes = await self._effective_permissions.resolve_api_codes(actor.user_id)
        return api_code in codes

    async def assert_api_permission(self, *, actor: CurrentActor, api_code: str) -> None:
        """断言操作者具备某个 API 权限（Spec `08 §10` 后端强制授权）。

        SUPER_ADMIN 的放行是**集中式 bypass**（Spec `10 §3`）：
        整个代码库中"因为我是 SUPER_ADMIN 所以放行"只出现在本方法里。
        """
        if await self.has_api_permission(actor=actor, api_code=api_code):
            return
        raise PermissionDeniedError(f"缺少 API 权限：{api_code}")

    async def assert_can_manage_roles(
        self,
        *,
        actor: CurrentActor,
        api_code: str = ApiPermissionCode.ROLE_MANAGE,
    ) -> None:
        """校验操作者是否有权管理角色（改数据范围、授予权限、改继承关系）。

        Phase 3 起不再是 INTERIM：判定依据是 **API Permission**
        （`ApiPermissionCode.ROLE_MANAGE`），SUPER_ADMIN 走集中式 bypass。

        判定入口集中在授权层，业务 Service 中**不出现**
        `if actor.is_super_admin` 分支（Spec `10 §3`）。
        """
        await self.assert_api_permission(actor=actor, api_code=api_code)

    async def assert_can_manage_permission_resources(self, *, actor: CurrentActor) -> None:
        """校验操作者是否有权管理权限资源定义（Phase 3 / DD-20）。"""
        await self.assert_api_permission(
            actor=actor, api_code=ApiPermissionCode.PERMISSION_RESOURCE_MANAGE
        )


__all__ = ["ApiPermissionCode", "AuthorizationService"]
