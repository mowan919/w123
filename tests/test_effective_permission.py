"""有效权限引擎测试（Task 3.11 / DD-19、DD-05、DD-06 已冻结）。

覆盖点
-----
- 多角色权限**取并集**（Spec `00 §1#2` / `15 D-002`）；
- 角色继承展开后继承权限计入（Spec `00 §1#3` / `03 §4`）；
- **DISABLED 角色不授予权限**——直接角色与"展开出来的祖先角色"都要筛，
  后者极易漏（只在展开前过滤一次的实现会把禁用祖先的权限放进来）；
- 字段权限按**最宽松者胜**合并（DD-06）；
- 数据范围按**可见集合求并**合并（DD-19），含 `SELF ∪ 其他` 的 `include_self`；
- SUPER_ADMIN 的集中式 bypass（Spec `10 §3`）；
- 轻量路径 `resolve_api_codes` 与完整路径 `build` 口径一致（否则会出现
  "判权放行、界面拒绝"或反之的双份真相）。

已登记缺陷（本文件用"特征化测试"钉住现状，**不自行修复**）
--------------------------------------------------------
**RISK-004**：`is_super_admin` 沿用既有集中式口径
（`list_role_codes_for_user` 只过滤 `deleted_at`，**不筛 status**），
而权限并集口径会筛 ACTIVE。因此"持有被禁用的 SUPER_ADMIN 角色"仍被当作
SUPER_ADMIN。该行为属已冻结集中式规则的语义变更，已登记待人类冻结。
本文件用 `TestRisk004Characterization` 明确钉住它 ——
这样任何修改都会让测试**显式失败**，而不是被悄悄改掉。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.auth.actor import SUPER_ADMIN_ROLE_CODE
from app.core.errors import NotFoundError
from app.core.scope import DataScope
from app.models import FieldAccessLevel, PermissionResourceType
from app.services.effective_permission import EffectivePermissionService
from app.services.role_inheritance import RoleInheritanceService
from tests.factories import (
    link_role_field_permission,
    link_role_inheritance,
    link_role_permission,
    link_user_role,
    make_department,
    make_permission_resource,
    make_role,
    make_user,
)

pytestmark = pytest.mark.integration

USER_ID = 3001
ROLE_A = 3010
ROLE_B = 3020
ROLE_C = 3030
PAGE_1 = 3101
PAGE_2 = 3102
PAGE_3 = 3103
API_1 = 3201
BUTTON_1 = 3301
FIELD_1 = 3401
FIELD_2 = 3402
DEPT_ROOT = 1
DEPT_CHILD = 2
DEPT_GRANDCHILD = 3
DEPT_FAR = 10


async def _seed_base(session, *, department_id: int = DEPT_CHILD) -> None:
    """部门 + 用户 + 三张页面 + 一个 API + 一个按钮 + 两个字段。"""
    await make_department(session, department_id=DEPT_ROOT, department_code="HQ")
    await make_department(
        session, department_id=DEPT_CHILD, department_code="RD", parent_id=DEPT_ROOT
    )
    await make_department(
        session, department_id=DEPT_GRANDCHILD, department_code="RD-FE", parent_id=DEPT_CHILD
    )
    await make_department(session, department_id=DEPT_FAR, department_code="FAR")

    await make_user(session, user_id=USER_ID, username="tester", department_id=department_id)

    for resource_id, code in ((PAGE_1, "p1"), (PAGE_2, "p2"), (PAGE_3, "p3")):
        await make_permission_resource(
            session,
            resource_id=resource_id,
            resource_type=PermissionResourceType.PAGE,
            resource_code=code,
            route_path=f"/{code}",
            component_path=code,
        )
    await make_permission_resource(
        session,
        resource_id=API_1,
        resource_type=PermissionResourceType.API,
        resource_code="ROLE_MANAGE",
        api_method="POST",
        api_path="/api/v1/admin/roles",
    )
    await make_permission_resource(
        session,
        resource_id=BUTTON_1,
        resource_type=PermissionResourceType.BUTTON,
        resource_code="p1:create",
        parent_id=PAGE_1,
    )
    await make_permission_resource(
        session,
        resource_id=FIELD_1,
        resource_type=PermissionResourceType.FIELD,
        resource_code="p1.phone",
        field_key="phone",
        owner_resource_id=PAGE_1,
    )
    await make_permission_resource(
        session,
        resource_id=FIELD_2,
        resource_type=PermissionResourceType.FIELD,
        resource_code="p1.email",
        field_key="email",
        owner_resource_id=PAGE_1,
    )


# ===========================================================================
# 并集与继承
# ===========================================================================
class TestUnionAcrossRoles:
    async def test_two_roles_union(self, db_session) -> None:
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A")
        await make_role(db_session, role_id=ROLE_B, role_code="B")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_B)
        await link_role_permission(db_session, role_id=ROLE_A, resource_id=PAGE_1)
        await link_role_permission(db_session, role_id=ROLE_B, resource_id=PAGE_2)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)

        assert context.direct_role_ids == frozenset({ROLE_A, ROLE_B})
        assert context.page_ids == frozenset({PAGE_1, PAGE_2})
        assert context.api_codes == frozenset()

    async def test_three_roles_union_including_button_and_api(self, db_session) -> None:
        await _seed_base(db_session)
        for role_id in (ROLE_A, ROLE_B, ROLE_C):
            await make_role(db_session, role_id=role_id, role_code=f"R{role_id}")
            await link_user_role(db_session, user_id=USER_ID, role_id=role_id)
        await link_role_permission(db_session, role_id=ROLE_A, resource_id=PAGE_1)
        await link_role_permission(db_session, role_id=ROLE_B, resource_id=BUTTON_1)
        await link_role_permission(db_session, role_id=ROLE_C, resource_id=API_1)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)

        assert context.page_ids == frozenset({PAGE_1})
        assert context.button_ids == frozenset({BUTTON_1})
        assert context.api_ids == frozenset({API_1})
        assert context.api_codes == frozenset({"ROLE_MANAGE"})

    async def test_inherited_permissions_are_counted(self, db_session) -> None:
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="CHILD")
        await make_role(db_session, role_id=ROLE_B, role_code="PARENT")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_role_inheritance(db_session, parent_role_id=ROLE_B, child_role_id=ROLE_A)
        await link_role_permission(db_session, role_id=ROLE_B, resource_id=PAGE_1)
        await link_role_permission(db_session, role_id=ROLE_A, resource_id=PAGE_2)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)

        assert context.direct_role_ids == frozenset({ROLE_A})
        assert context.inherited_role_ids == frozenset({ROLE_B})
        assert context.effective_role_ids == frozenset({ROLE_A, ROLE_B})
        assert context.page_ids == frozenset({PAGE_1, PAGE_2})

    async def test_grandparent_is_reached_transitively(self, db_session) -> None:
        await _seed_base(db_session)
        for role_id in (ROLE_A, ROLE_B, ROLE_C):
            await make_role(db_session, role_id=role_id, role_code=f"R{role_id}")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_role_inheritance(db_session, parent_role_id=ROLE_B, child_role_id=ROLE_A)
        await link_role_inheritance(db_session, parent_role_id=ROLE_C, child_role_id=ROLE_B)
        await link_role_permission(db_session, role_id=ROLE_C, resource_id=PAGE_1)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)

        assert context.effective_role_ids == frozenset({ROLE_A, ROLE_B, ROLE_C})
        assert context.page_ids == frozenset({PAGE_1})

    async def test_permissions_change_takes_effect_immediately(self, db_session) -> None:
        """Spec 00 §1#5 / 15 D-005：权限变更立即生效（Phase 3 不引入缓存）。"""
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)

        service = EffectivePermissionService(db_session)
        assert (await service.build(user_id=USER_ID)).page_ids == frozenset()

        await link_role_permission(db_session, role_id=ROLE_A, resource_id=PAGE_1)
        assert (await service.build(user_id=USER_ID)).page_ids == frozenset({PAGE_1})


# ===========================================================================
# 禁用角色不授予权限
# ===========================================================================
class TestDisabledRolesAreExcluded:
    """禁用 / 逻辑删除的角色不得授予任何权限。

    ⚠️ 这里有一个**已登记的表示层不一致**（INTERIM，待 Phase 8 前裁定）：
    "用户没有任何**有效**角色"时，`build()` 会因 `configs` 为空而抛
    `ValueError`（fail-closed），而"范围内没有任何部门"却能表示为
    合法的空集合 `ResolvedScope`。两者都拒绝，但表示形式不同；
    轻量路径 `resolve_api_codes` 则**不抛错**、直接返回空集合。

    两种做法都满足 Spec `11 §5` 的 fail-closed 取向（都不放行），
    但会让 Phase 8 的 HTTP 层分别得到 500 与 403/空权限。
    本 Phase 不自行决定统一口径，只把现状钉住并在交付报告中登记。
    """

    async def test_disabled_direct_role_grants_nothing(self, db_session) -> None:
        from app.models import RoleStatus

        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A", status=RoleStatus.DISABLED)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_role_permission(db_session, role_id=ROLE_A, resource_id=PAGE_1)

        service = EffectivePermissionService(db_session)
        # fail-closed：解析不出范围 → 抛错而非放行（绝不退化为全局）。
        with pytest.raises(ValueError, match="无任何角色范围配置"):
            await service.build(user_id=USER_ID)
        # 轻量判权路径同样不授予任何权限。
        assert await service.resolve_api_codes(USER_ID) == frozenset()

    async def test_disabled_ancestor_grants_nothing(self, db_session) -> None:
        """**最容易漏掉的一步**：展开出来的祖先必须**再筛一次**状态。

        只做直接角色的状态过滤，会让"被禁用的父角色"把权限继续传下来 ——
        此时"禁用角色"这个动作对继承场景完全失效。
        """
        from app.models import RoleStatus

        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="CHILD")
        await make_role(db_session, role_id=ROLE_B, role_code="PARENT", status=RoleStatus.DISABLED)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_role_inheritance(db_session, parent_role_id=ROLE_B, child_role_id=ROLE_A)
        await link_role_permission(db_session, role_id=ROLE_B, resource_id=PAGE_1)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)

        assert context.effective_role_ids == frozenset({ROLE_A})
        assert context.page_ids == frozenset(), "禁用祖先的权限不得被继承"

    async def test_soft_deleted_role_is_excluded(self, db_session) -> None:
        from app.db.base import utc_now

        await _seed_base(db_session)
        role = await make_role(db_session, role_id=ROLE_A, role_code="GONE")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_role_permission(db_session, role_id=ROLE_A, resource_id=PAGE_1)
        role.deleted_at = utc_now()
        await db_session.flush()
        assert role.deleted_at is not None

        # 唯一角色被逻辑删除 → 同"无有效角色"，不授予任何权限。
        with pytest.raises(ValueError, match="无任何角色范围配置"):
            await EffectivePermissionService(db_session).build(user_id=USER_ID)

    async def test_disabled_resource_is_excluded(self, db_session) -> None:
        """资源被禁用后授权仍在表里，但不得进入有效权限。"""
        from app.models import PermissionResource, PermissionStatus

        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_role_permission(db_session, role_id=ROLE_A, resource_id=PAGE_1)

        resource = (
            await db_session.execute(
                select(PermissionResource).where(PermissionResource.id == PAGE_1)
            )
        ).scalar_one()
        resource.status = PermissionStatus.DISABLED
        await db_session.flush()

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        assert context.page_ids == frozenset()
        # 授权行本身没有被删除 —— 禁用是可逆的，恢复后可立即生效。
        assert context.resource_ids[PermissionResourceType.PAGE] == frozenset()


# ===========================================================================
# 字段权限合并（DD-06）
# ===========================================================================
class TestFieldPermissionMerge:
    async def test_most_permissive_across_roles(self, db_session) -> None:
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A")
        await make_role(db_session, role_id=ROLE_B, role_code="B")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_B)
        await link_role_field_permission(
            db_session, role_id=ROLE_A, field_id=FIELD_1, access_level=FieldAccessLevel.HIDDEN
        )
        await link_role_field_permission(
            db_session, role_id=ROLE_B, field_id=FIELD_1, access_level=FieldAccessLevel.EDITABLE
        )
        await link_role_field_permission(
            db_session, role_id=ROLE_B, field_id=FIELD_2, access_level=FieldAccessLevel.READ_ONLY
        )

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        policies = context.field_policy_map()

        assert policies == {
            "phone": FieldAccessLevel.EDITABLE,
            "email": FieldAccessLevel.READ_ONLY,
        }

    async def test_hidden_does_not_veto_visible(self, db_session) -> None:
        """DD-06 冻结方向的显式后果：HIDDEN 不能一票否决其他角色的 VISIBLE。"""
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A")
        await make_role(db_session, role_id=ROLE_B, role_code="B")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_B)
        await link_role_field_permission(
            db_session, role_id=ROLE_A, field_id=FIELD_1, access_level=FieldAccessLevel.HIDDEN
        )
        await link_role_field_permission(
            db_session, role_id=ROLE_B, field_id=FIELD_1, access_level=FieldAccessLevel.VISIBLE
        )

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        assert context.field_policy_map()["phone"] is FieldAccessLevel.VISIBLE

    async def test_field_policy_carries_owner_and_key(self, db_session) -> None:
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_role_field_permission(
            db_session, role_id=ROLE_A, field_id=FIELD_1, access_level=FieldAccessLevel.VISIBLE
        )

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        policy = context.field_policies[0]
        assert policy.field_id == FIELD_1
        assert policy.field_key == "phone"
        assert policy.owner_resource_id == PAGE_1
        assert policy.resource_code == "p1.phone"

    async def test_disabled_field_resource_is_excluded(self, db_session) -> None:
        from sqlalchemy import select

        from app.models import PermissionResource, PermissionStatus

        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_role_field_permission(
            db_session, role_id=ROLE_A, field_id=FIELD_1, access_level=FieldAccessLevel.VISIBLE
        )
        resource = (
            await db_session.execute(
                select(PermissionResource).where(PermissionResource.id == FIELD_1)
            )
        ).scalar_one()
        resource.status = PermissionStatus.DISABLED
        await db_session.flush()

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        assert context.field_policies == ()


# ===========================================================================
# 数据范围合并（DD-19）
# ===========================================================================
class TestDataScopeMerge:
    async def test_department_children_and_custom_union(self, db_session) -> None:
        await _seed_base(db_session)
        await make_role(
            db_session,
            role_id=ROLE_A,
            role_code="A",
            data_scope=DataScope.DEPARTMENT_CHILDREN,
        )
        await make_role(db_session, role_id=ROLE_B, role_code="B", data_scope=DataScope.CUSTOM)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_B)

        from tests.factories import link_role_custom_scope

        await link_role_custom_scope(db_session, role_id=ROLE_B, department_id=DEPT_FAR)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        # DEPARTMENT_CHILDREN(dept=2) = {2, 3}；CUSTOM = {10} → 并集。
        assert context.data_scope is not None
        assert context.data_scope.department_ids == frozenset(
            {DEPT_CHILD, DEPT_GRANDCHILD, DEPT_FAR}
        )
        assert context.data_scope.restrict_to_actor is False
        assert context.data_scope.include_self is False

    async def test_all_wins_over_everything(self, db_session) -> None:
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A", data_scope=DataScope.ALL)
        await make_role(db_session, role_id=ROLE_B, role_code="B", data_scope=DataScope.DEPARTMENT)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_B)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        assert context.data_scope is not None
        assert context.data_scope.is_unrestricted_departments is True
        assert context.data_scope.department_ids is None

    async def test_self_plus_department_keeps_self_extra(self, db_session) -> None:
        """`SELF ∪ DEPARTMENT_CHILDREN` = 部门集合 **外加** 本人（DD-19）。

        这正是 `include_self` 存在的理由：既有的 `restrict_to_actor`
        只能表达"**仅**本人"，无法表达"部门集合 ∪ 本人"。
        """
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A", data_scope=DataScope.SELF)
        await make_role(
            db_session,
            role_id=ROLE_B,
            role_code="B",
            data_scope=DataScope.DEPARTMENT_CHILDREN,
        )
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_B)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        scope = context.data_scope
        assert scope is not None
        assert scope.restrict_to_actor is False
        assert scope.include_self is True
        assert scope.department_ids == frozenset({DEPT_CHILD, DEPT_GRANDCHILD})
        # 本人所在部门 2 已在集合内；本人用户仍必须被放行。
        assert scope.allows_user(user_id=USER_ID, department_id=None) is True

    async def test_all_self_collapses_to_self_only(self, db_session) -> None:
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A", data_scope=DataScope.SELF)
        await make_role(db_session, role_id=ROLE_B, role_code="B", data_scope=DataScope.SELF)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_B)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        scope = context.data_scope
        assert scope is not None
        assert scope.restrict_to_actor is True
        assert scope.department_ids == frozenset()
        assert scope.allows_user(user_id=USER_ID, department_id=None) is True
        assert scope.allows_user(user_id=999_999, department_id=None) is False

    async def test_custom_without_configured_departments_denies(self, db_session) -> None:
        """CUSTOM 未配置 → 什么都不看不到（fail-closed，绝不退化为全局）。"""
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A", data_scope=DataScope.CUSTOM)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        scope = context.data_scope
        assert scope is not None
        assert scope.department_ids == frozenset()
        assert scope.denies_all_users is True


# ===========================================================================
# SUPER_ADMIN bypass
# ===========================================================================
class TestSuperAdminBypass:
    async def test_super_admin_has_every_api_permission(self, db_session) -> None:
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code=SUPER_ADMIN_ROLE_CODE)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        assert context.is_super_admin is True
        assert context.has_api_permission("ANYTHING_AT_ALL") is True

    async def test_super_admin_data_scope_is_global(self, db_session) -> None:
        await _seed_base(db_session)
        await make_role(
            db_session,
            role_id=ROLE_A,
            role_code=SUPER_ADMIN_ROLE_CODE,
            data_scope=DataScope.DEPARTMENT,
        )
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        assert context.data_scope is not None
        assert context.data_scope.is_unrestricted_departments is True

    async def test_normal_user_needs_explicit_api_grant(self, db_session) -> None:
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        assert context.is_super_admin is False
        assert context.has_api_permission("ROLE_MANAGE") is False

        await link_role_permission(db_session, role_id=ROLE_A, resource_id=API_1)
        granted = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        assert granted.has_api_permission("ROLE_MANAGE") is True


# ===========================================================================
# 轻量路径一致性
# ===========================================================================
class TestLightweightPathConsistency:
    async def test_resolve_api_codes_matches_build(self, db_session) -> None:
        """两条路径必须同口径，否则会出现"判权放行、界面拒绝"的双份真相。"""
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="CHILD")
        await make_role(db_session, role_id=ROLE_B, role_code="PARENT")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_role_inheritance(db_session, parent_role_id=ROLE_B, child_role_id=ROLE_A)
        await link_role_permission(db_session, role_id=ROLE_B, resource_id=API_1)

        service = EffectivePermissionService(db_session)
        assert (
            await service.resolve_api_codes(USER_ID)
            == (await service.build(user_id=USER_ID)).api_codes
        )

    async def test_resolve_api_codes_ignores_disabled_roles(self, db_session) -> None:
        from app.models import RoleStatus

        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A", status=RoleStatus.DISABLED)
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_role_permission(db_session, role_id=ROLE_A, resource_id=API_1)

        service = EffectivePermissionService(db_session)
        assert await service.resolve_api_codes(USER_ID) == frozenset()

    async def test_resolve_api_codes_without_roles_is_empty(self, db_session) -> None:
        await _seed_base(db_session)
        service = EffectivePermissionService(db_session)
        assert await service.resolve_api_codes(USER_ID) == frozenset()


# ===========================================================================
# 版本、错误与预览
# ===========================================================================
class TestVersionAndPreview:
    async def test_context_carries_permission_version(self, db_session) -> None:
        from app.repositories.permission import PermissionVersionRepository

        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="A")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await PermissionVersionRepository(db_session).bump()
        await PermissionVersionRepository(db_session).bump()

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        assert context.version == 2

    async def test_missing_user_returns_404(self, db_session) -> None:
        await _seed_base(db_session)
        service = EffectivePermissionService(db_session)
        with pytest.raises(NotFoundError, match="用户不存在"):
            await service.build(user_id=999_999)

    async def test_preview_reports_role_sources_and_edges(self, db_session) -> None:
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="CHILD", role_name="子角色")
        await make_role(db_session, role_id=ROLE_B, role_code="PARENT", role_name="父角色")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_role_inheritance(db_session, parent_role_id=ROLE_B, child_role_id=ROLE_A)

        preview = await EffectivePermissionService(db_session).preview(user_id=USER_ID)

        summarized = {item[0]: item for item in preview.role_summaries}
        assert summarized[ROLE_A][1] == "CHILD"
        assert summarized[ROLE_A][3] is True  # 直接持有
        assert summarized[ROLE_B][3] is False  # 继承而来
        assert preview.inheritance_edges == frozenset({(ROLE_B, ROLE_A)})

    async def test_role_less_user_fails_closed_with_error(self, db_session) -> None:
        """无角色的用户**不**得到一个"看起来正常"的权限上下文。

        `DataScopeResolver.resolve_for_subject` 在配置集合为空时抛错，
        而不是回落到 ALL —— fail-closed（Spec `11 §5`）：
        "解析不出具体范围"必须收敛为拒绝，绝不退化为全局。
        """
        await _seed_base(db_session)
        service = EffectivePermissionService(db_session)
        with pytest.raises(ValueError, match="无任何角色范围配置"):
            await service.build(user_id=USER_ID)


# ===========================================================================
# 特征化测试：已登记缺陷 RISK-004
# ===========================================================================
class TestRisk004Characterization:
    """钉住 **RISK-004** 的现状，避免它被静默改变。

    现状：`is_super_admin` 由 `list_role_codes_for_user` 推导，
    该查询**只过滤 `deleted_at`、不过滤 `status`**；
    而权限并集（`list_active_role_ids_for_user`）**会**过滤 ACTIVE。
    两者口径不同，导致"持有被禁用的 SUPER_ADMIN 角色"仍被视为 SUPER_ADMIN，
    从而拿到全局数据范围与全部 API 权限。

    这**不是**期望行为，而是已冻结集中式规则的既有语义。
    本 Phase 不得自行修改（属语义变更），因此这里显式记录现状：
    将来冻结并修复后，这两个用例会失败 —— 那时应当**改写它们**，
    而不是绕过。
    """

    async def test_disabled_super_admin_role_still_bypasses(self, db_session) -> None:
        from app.models import RoleStatus

        await _seed_base(db_session)
        await make_role(
            db_session,
            role_id=ROLE_A,
            role_code=SUPER_ADMIN_ROLE_CODE,
            status=RoleStatus.DISABLED,
        )
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)

        # 权限并集口径：禁用角色不参与 → 没有任何有效角色与资源。
        assert context.effective_role_ids == frozenset()
        assert context.page_ids == frozenset()
        # 集中式口径：仍然被判定为 SUPER_ADMIN（RISK-004）。
        assert context.is_super_admin is True
        assert context.has_api_permission("ANYTHING_AT_ALL") is True

    async def test_disabled_super_admin_role_still_gets_global_scope(self, db_session) -> None:
        from app.models import RoleStatus

        await _seed_base(db_session)
        await make_role(
            db_session,
            role_id=ROLE_A,
            role_code=SUPER_ADMIN_ROLE_CODE,
            status=RoleStatus.DISABLED,
        )
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        assert context.data_scope is not None
        assert context.data_scope.is_unrestricted_departments is True


# ===========================================================================
# 服务层与仓储层的一致性
# ===========================================================================
class TestInheritanceServiceDelegation:
    async def test_effective_engine_and_inheritance_service_agree(self, db_session) -> None:
        """两个入口必须给出同一套展开结果 —— 否则"预览"与"判权"会不一致。

        `RoleInheritanceService.expand_role_ids` 是对外入口（预览用），
        `EffectivePermissionService.build` 是判权入口；
        两者底层共用同一仓储方法，本用例把它钉住，
        防止将来有人给其中一条路径单独加过滤条件。
        """
        await _seed_base(db_session)
        await make_role(db_session, role_id=ROLE_A, role_code="CHILD")
        await make_role(db_session, role_id=ROLE_B, role_code="PARENT")
        await link_user_role(db_session, user_id=USER_ID, role_id=ROLE_A)
        await link_role_inheritance(db_session, parent_role_id=ROLE_B, child_role_id=ROLE_A)

        expanded = await RoleInheritanceService(db_session).expand_role_ids(frozenset({ROLE_A}))
        assert expanded == frozenset({ROLE_A, ROLE_B})

        context = await EffectivePermissionService(db_session).build(user_id=USER_ID)
        assert context.effective_role_ids == expanded
