"""前端动态权限契约服务测试（Phase 8 / Spec `09`）。

覆盖 Verification `008-dynamic-permission.md` 的前六项
（页面 / 菜单 / 按钮 / API / 字段 / data scope）在**服务层**的取值，
以及三项容易写错的语义：

1. **菜单的 page_ids 必须与"已授权页面"求交**（`09 §3`）——
   只下发"菜单关联的页面"会把无权页面泄漏成菜单入口；
2. **停用 / 已删除的资源必须退出契约**（授权行不会自动清理）；
3. **无有效角色的用户必须得到拒绝型上下文而不是异常**（DD-21）——
   这是"新账号尚未分配角色"这一**正常状态**的可渲染表达。

SUPER_ADMIN 的 bypass 表达与"字段权限不做 bypass"这条刻意的不对称，
是 Phase 8 新增的 JUDGMENT-8-01，同样在此钉住。
"""

from __future__ import annotations

import pytest

from app.auth.actor import SUPER_ADMIN_ROLE_CODE
from app.core.scope import DataScope
from app.db.base import utc_now
from app.models.enums import (
    FieldAccessLevel,
    PermissionResourceType,
    PermissionStatus,
)
from app.services.permission_contract import PermissionContractService
from tests.factories import (
    link_menu_page,
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

DEPT_ID = 60001
CHILD_DEPT_ID = 60002

ROLE_A = 60011
ROLE_B = 60012
ROLE_CHILD = 60013
ROLE_SUPER = 60014
ROLE_EMPTY = 60015

USER_ID = 60101
SUPER_USER_ID = 60102
ROLE_LESS_USER_ID = 60103
INHERITING_USER_ID = 60104

# 资源 ID 分段：PAGE=602xx / MENU=603xx / BUTTON=604xx / API=605xx / FIELD=606xx
PAGE_LIST = 60201
PAGE_DETAIL = 60202
PAGE_DISABLED = 60203
PAGE_DELETED = 60204

MENU_MAIN = 60301
MENU_SUB = 60302
MENU_DISABLED = 60303

BUTTON_CREATE = 60401
BUTTON_DISABLED = 60402

API_USER_CREATE = 60501
API_ROLE_MANAGE = 60502

FIELD_PHONE = 60601
FIELD_EMAIL = 60602


async def _seed(session) -> None:
    """构造一棵"配置面"资源树 + 若干角色。"""
    await make_department(session, department_id=DEPT_ID, department_code="P8-DEPT")
    await make_department(
        session, department_id=CHILD_DEPT_ID, department_code="P8-CHILD", parent_id=DEPT_ID
    )

    for role_id, code, scope in (
        (ROLE_A, "P8_A", DataScope.DEPARTMENT_CHILDREN),
        (ROLE_B, "P8_B", DataScope.SELF),
        (ROLE_CHILD, "P8_CHILD", DataScope.DEPARTMENT_CHILDREN),
        (ROLE_SUPER, SUPER_ADMIN_ROLE_CODE, DataScope.ALL),
        (ROLE_EMPTY, "P8_EMPTY", DataScope.DEPARTMENT_CHILDREN),
    ):
        await make_role(session, role_id=role_id, role_code=code, data_scope=scope)

    # ---- 页面 ----
    await make_permission_resource(
        session,
        resource_id=PAGE_LIST,
        resource_type=PermissionResourceType.PAGE,
        resource_code="user:list",
        resource_name="用户列表",
        sort_order=2,
        route_path="/users",
        component_path="views/user/list.vue",
    )
    await make_permission_resource(
        session,
        resource_id=PAGE_DETAIL,
        resource_type=PermissionResourceType.PAGE,
        resource_code="user:detail",
        resource_name="用户详情",
        sort_order=1,
        route_path="/users/:id",
        component_path="views/user/detail.vue",
    )
    # 已停用 / 已逻辑删除的页面（授权行仍然存在，见下方授权）
    await make_permission_resource(
        session,
        resource_id=PAGE_DISABLED,
        resource_type=PermissionResourceType.PAGE,
        resource_code="user:disabled",
        route_path="/disabled",
        component_path="views/disabled.vue",
        status=PermissionStatus.DISABLED,
    )
    deleted_page = await make_permission_resource(
        session,
        resource_id=PAGE_DELETED,
        resource_type=PermissionResourceType.PAGE,
        resource_code="user:deleted",
        route_path="/deleted",
        component_path="views/deleted.vue",
    )
    # 真正逻辑删除。`role_permissions` 里仍有指向它的授权行（见下方 ROLE_CHILD），
    # 用来验证契约只认"未删除"这一准入口径 —— 直接写库是刻意的：
    # 服务层删除会因"仍有角色授权"而拒绝（引用检查），造不出这个形态。
    deleted_page.deleted_at = utc_now()
    await session.flush()

    # ---- 菜单（含层级与图标） ----
    await make_permission_resource(
        session,
        resource_id=MENU_MAIN,
        resource_type=PermissionResourceType.MENU,
        resource_code="nav:system",
        resource_name="系统管理",
        sort_order=1,
        icon="settings",
    )
    await make_permission_resource(
        session,
        resource_id=MENU_SUB,
        resource_type=PermissionResourceType.MENU,
        resource_code="nav:system:user",
        resource_name="用户",
        parent_id=MENU_MAIN,
        sort_order=2,
        icon="user",
    )
    await make_permission_resource(
        session,
        resource_id=MENU_DISABLED,
        resource_type=PermissionResourceType.MENU,
        resource_code="nav:disabled",
        status=PermissionStatus.DISABLED,
    )

    # ---- 按钮（必须挂在 PAGE 下） ----
    await make_permission_resource(
        session,
        resource_id=BUTTON_CREATE,
        resource_type=PermissionResourceType.BUTTON,
        resource_code="user:create",
        resource_name="新建用户",
        parent_id=PAGE_LIST,
        sort_order=3,
    )
    await make_permission_resource(
        session,
        resource_id=BUTTON_DISABLED,
        resource_type=PermissionResourceType.BUTTON,
        resource_code="user:delete",
        parent_id=PAGE_LIST,
        status=PermissionStatus.DISABLED,
    )

    # ---- API（形状约束要求 method + path 同时给出） ----
    await make_permission_resource(
        session,
        resource_id=API_USER_CREATE,
        resource_type=PermissionResourceType.API,
        resource_code="USER_CREATE",
        resource_name="创建用户",
        parent_id=PAGE_LIST,
        api_method="POST",
        api_path="/api/v1/admin/users",
    )
    await make_permission_resource(
        session,
        resource_id=API_ROLE_MANAGE,
        resource_type=PermissionResourceType.API,
        resource_code="ROLE_MANAGE",
        resource_name="角色管理",
        api_method="GET",
        api_path="/api/v1/admin/roles",
    )

    # ---- 字段（归属 PAGE） ----
    await make_permission_resource(
        session,
        resource_id=FIELD_PHONE,
        resource_type=PermissionResourceType.FIELD,
        resource_code="user:phone",
        field_key="phone",
        owner_resource_id=PAGE_LIST,
    )
    await make_permission_resource(
        session,
        resource_id=FIELD_EMAIL,
        resource_type=PermissionResourceType.FIELD,
        resource_code="user:email",
        field_key="email",
        owner_resource_id=PAGE_LIST,
    )

    # ---- Menu → Page 多对多：一个菜单关联**多个**页面（00 §1#4） ----
    await link_menu_page(session, menu_id=MENU_MAIN, page_id=PAGE_LIST)
    await link_menu_page(session, menu_id=MENU_MAIN, page_id=PAGE_DETAIL)
    await link_menu_page(session, menu_id=MENU_MAIN, page_id=PAGE_DISABLED)
    await link_menu_page(session, menu_id=MENU_SUB, page_id=PAGE_LIST)

    # ---- 角色授权 ----
    for resource_id in (
        PAGE_LIST,
        PAGE_DISABLED,
        MENU_MAIN,
        MENU_SUB,
        MENU_DISABLED,
        BUTTON_CREATE,
        BUTTON_DISABLED,
        API_USER_CREATE,
        API_ROLE_MANAGE,
    ):
        await link_role_permission(session, role_id=ROLE_A, resource_id=resource_id)
    # ROLE_A 的字段等级：HIDDEN；ROLE_B 再授予 VISIBLE → 合并应取 VISIBLE
    await link_role_field_permission(
        session, role_id=ROLE_A, field_id=FIELD_PHONE, access_level=FieldAccessLevel.HIDDEN
    )
    await link_role_field_permission(
        session, role_id=ROLE_A, field_id=FIELD_EMAIL, access_level=FieldAccessLevel.READ_ONLY
    )

    # 只授权 PAGE_DETAIL（用于"菜单 ∩ 已授权页面"的求交断言）
    await link_role_permission(session, role_id=ROLE_B, resource_id=PAGE_DETAIL)
    await link_role_field_permission(
        session, role_id=ROLE_B, field_id=FIELD_PHONE, access_level=FieldAccessLevel.VISIBLE
    )

    # 继承：ROLE_CHILD 继承 ROLE_A（子角色获得父角色的全部权限）
    await link_role_inheritance(session, parent_role_id=ROLE_A, child_role_id=ROLE_CHILD)
    await link_role_permission(session, role_id=ROLE_CHILD, resource_id=PAGE_DELETED)

    # ---- 用户 ----
    await make_user(
        session,
        user_id=USER_ID,
        username="p8-contract-user",
        department_id=DEPT_ID,
        password_changed_at=None,
    )
    await link_user_role(session, user_id=USER_ID, role_id=ROLE_A)
    await link_user_role(session, user_id=USER_ID, role_id=ROLE_B)

    await make_user(
        session, user_id=SUPER_USER_ID, username="p8-contract-super", department_id=DEPT_ID
    )
    await link_user_role(session, user_id=SUPER_USER_ID, role_id=ROLE_SUPER)

    await make_user(
        session, user_id=ROLE_LESS_USER_ID, username="p8-contract-norole", department_id=DEPT_ID
    )

    await make_user(
        session, user_id=INHERITING_USER_ID, username="p8-contract-inherit", department_id=DEPT_ID
    )
    await link_user_role(session, user_id=INHERITING_USER_ID, role_id=ROLE_CHILD)


class TestBinaryPermissions:
    """四类二元权限（page / menu / button / api）的输出。"""

    async def test_role_grants_are_rendered_with_metadata(self, db_session) -> None:
        """每一项都必须带上前端生成路由/导航所需的元数据。

        只下发 ID 是不够的：前端无法从 `60201` 推出 `/users` 与组件路径，
        也就无法"根据后端配置动态生成 route"（`09 §3`）——
        那样等于把路由表又硬编码回前端。
        """
        await _seed(db_session)
        contract = await PermissionContractService(db_session).build(user_id=USER_ID)

        pages = {page.resource_code: page for page in contract.pages}
        assert set(pages) == {"user:list", "user:detail"}
        assert pages["user:list"].route_path == "/users"
        assert pages["user:list"].component_path == "views/user/list.vue"

        menus = {menu.resource.resource_code: menu for menu in contract.menus}
        assert set(menus) == {"nav:system", "nav:system:user"}
        assert menus["nav:system"].resource.icon == "settings"
        assert menus["nav:system:user"].resource.parent_id == MENU_MAIN

        buttons = {button.resource_code for button in contract.buttons}
        assert buttons == {"user:create"}
        assert next(iter(contract.buttons)).parent_id == PAGE_LIST

        apis = {api.resource_code: api for api in contract.apis}
        assert set(apis) == {"USER_CREATE", "ROLE_MANAGE"}
        assert apis["USER_CREATE"].api_method == "POST"
        assert apis["USER_CREATE"].api_path == "/api/v1/admin/users"

    async def test_disabled_and_deleted_resources_are_excluded(self, db_session) -> None:
        """停用 / 逻辑删除的资源必须退出契约，**即使授权行仍然存在**。

        这是最容易漏的一条：`role_permissions` 不会因为资源被停用而清理，
        若契约直接信授权行，管理员看到的菜单里会出现"点了必然 403"的入口 ——
        看起来是前端 bug，实际是契约泄漏了失效资源。
        """
        await _seed(db_session)
        contract = await PermissionContractService(db_session).build(user_id=USER_ID)

        assert PAGE_DISABLED not in {page.id for page in contract.pages}
        assert MENU_DISABLED not in {menu.resource.id for menu in contract.menus}
        assert BUTTON_DISABLED not in {button.id for button in contract.buttons}

        # 页面本身已删除（`user:deleted` 由 ROLE_CHILD 授权，但该用户不含该角色）
        assert PAGE_DELETED not in {page.id for page in contract.pages}

    async def test_menu_pages_are_intersected_with_granted_pages(self, db_session) -> None:
        """菜单的 `page_ids` = 菜单关联页面 ∩ 用户已授权页面。

        `MENU_MAIN` 关联了 3 个页面（list / detail / disabled），
        该用户有 list 与 detail 的授权 → 交集必须是这两个，
        **不含**已停用的 disabled，也**不含**未关联的页面。
        """
        await _seed(db_session)
        contract = await PermissionContractService(db_session).build(user_id=USER_ID)
        menus = {menu.resource.resource_code: menu for menu in contract.menus}

        assert set(menus["nav:system"].page_ids) == {PAGE_LIST, PAGE_DETAIL}
        assert set(menus["nav:system:user"].page_ids) == {PAGE_LIST}

    async def test_ordering_follows_sort_order(self, db_session) -> None:
        """输出顺序必须与后台配置的 `sort_order` 一致（其次是 ID）。

        若顺序由数据库任意决定，管理员"把页面拖到第一位"会在前端无效果，
        而这类不一致极难被归因。
        """
        await _seed(db_session)
        contract = await PermissionContractService(db_session).build(user_id=USER_ID)
        assert [page.id for page in contract.pages] == [PAGE_DETAIL, PAGE_LIST]

    async def test_inherited_role_permissions_are_included(self, db_session) -> None:
        """继承链计入有效权限（`00 §1#3` / DD-05）。

        `ROLE_CHILD` 直接授权的只有已删除的 `PAGE_DELETED`（因此不可见），
        其余可见权限**全部来自继承的 `ROLE_A`** ——
        `user:list` 正是继承来的。而 `user:detail` 属 `ROLE_B`，
        该用户不含此角色，**不得**出现：这条否证了"把别人的权限一并算上"。
        """
        await _seed(db_session)
        contract = await PermissionContractService(db_session).build(user_id=INHERITING_USER_ID)
        assert contract.context.direct_role_ids == frozenset({ROLE_CHILD})
        assert contract.context.inherited_role_ids == frozenset({ROLE_A})
        assert {page.resource_code for page in contract.pages} == {"user:list"}


class TestFieldsAndScope:
    """字段策略与数据范围。"""

    async def test_field_levels_are_merged_most_permissive_wins(self, db_session) -> None:
        """多角色字段等级按"最宽松者胜"合并（DD-06 冻结）。

        `phone` 被 ROLE_A 授予 HIDDEN、被 ROLE_B 授予 VISIBLE →
        有效等级必须是 VISIBLE。HIDDEN **不能**否决其他角色的 VISIBLE，
        这是 DD-06 的显式后果，不得被当成缺陷改掉。
        """
        await _seed(db_session)
        context = (await PermissionContractService(db_session).build(user_id=USER_ID)).context
        levels = context.field_policy_map()
        assert levels["phone"] is FieldAccessLevel.VISIBLE
        assert levels["email"] is FieldAccessLevel.READ_ONLY

    async def test_field_policies_carry_owner_page(self, db_session) -> None:
        """字段必须能反查所属页面（前端按页面组织字段行为，`09 §6`）。"""
        await _seed(db_session)
        context = (await PermissionContractService(db_session).build(user_id=USER_ID)).context
        owners = {policy.field_key: policy.owner_resource_id for policy in context.field_policies}
        assert owners == {"phone": PAGE_LIST, "email": PAGE_LIST}

    async def test_data_scope_is_resolved_and_merged(self, db_session) -> None:
        """数据范围输出的是**已解析**的部门集合（含后代），不是策略名。

        `DEPARTMENT_CHILDREN` 必须展开为"本部门 + 后代"，
        否则前端无从判断"这个下拉框该列哪些部门"。
        """
        await _seed(db_session)
        context = (await PermissionContractService(db_session).build(user_id=USER_ID)).context
        scope = context.data_scope
        assert scope is not None
        # ROLE_A = DEPARTMENT_CHILDREN(本部门+子部门)；ROLE_B = SELF → 求并后额外含本人
        assert scope.department_ids == frozenset({DEPT_ID, CHILD_DEPT_ID})
        assert scope.include_self is True
        assert scope.allows_department(CHILD_DEPT_ID) is True

    async def test_permission_version_is_reported(self, db_session) -> None:
        """`09 §2` 要求返回 permission version（DD-04 未冻结其缓存语义）。"""
        await _seed(db_session)
        context = (await PermissionContractService(db_session).build(user_id=USER_ID)).context
        assert context.version >= 0


class TestSuperAdmin:
    """SUPER_ADMIN 的契约表达（JUDGMENT-8-01）。"""

    async def test_super_admin_receives_all_active_resources(self, db_session) -> None:
        """超管的"有效权限"就是全部有效资源（`10 §3` 集中式 bypass 的事实表达）。

        若这里按 `role_permissions` 逐条读，超管会拿到**空集合** ——
        前端渲染出一个空后台，而真实授权是"全部"。那不是保守，而是
        **对授权状态的错误表述**。
        """
        await _seed(db_session)
        contract = await PermissionContractService(db_session).build(user_id=SUPER_USER_ID)
        assert contract.context.is_super_admin is True

        assert {page.id for page in contract.pages} == {PAGE_LIST, PAGE_DETAIL}
        assert {menu.resource.id for menu in contract.menus} == {MENU_MAIN, MENU_SUB}
        assert {button.id for button in contract.buttons} == {BUTTON_CREATE}
        assert {api.id for api in contract.apis} == {API_USER_CREATE, API_ROLE_MANAGE}

    async def test_super_admin_field_policies_are_not_bypassed(self, db_session) -> None:
        """**字段权限刻意不做 bypass**，且这一点必须被钉住。

        后端没有任何字段级 bypass：`field_policies` 的唯一消费方就是本契约。
        若超管在这里"额外获得全部字段可编辑"，前端会展示出后端实际并不承认的
        字段能力 —— 契约与行为不一致比"少显示"危险得多。
        因此超管得到空字段列表，与"未授权字段按 HIDDEN 处理"的约定一致。
        """
        await _seed(db_session)
        context = (await PermissionContractService(db_session).build(user_id=SUPER_USER_ID)).context
        assert context.is_super_admin is True
        assert context.field_policies == ()

    async def test_super_admin_data_scope_is_unrestricted(self, db_session) -> None:
        """超管的数据范围是全局（部门维度不限制）。"""
        await _seed(db_session)
        context = (await PermissionContractService(db_session).build(user_id=SUPER_USER_ID)).context
        scope = context.data_scope
        assert scope is not None
        assert scope.is_unrestricted_departments is True


class TestEmptyRoleUser:
    """无有效角色的用户（DD-21 的保守技术处理）。"""

    async def test_role_less_user_gets_a_deny_type_contract(self, db_session) -> None:
        """无角色 → 空权限 + 空范围，**不抛异常**。

        "新账号尚未分配角色"是正常状态，不是服务器错误。
        若这里抛错，HTTP 层会把它变成 500，而正确表现是
        "你暂时没有任何权限"（前端渲染无权限页）。
        """
        await _seed(db_session)
        contract = await PermissionContractService(db_session).build(user_id=ROLE_LESS_USER_ID)

        assert contract.pages == ()
        assert contract.menus == ()
        assert contract.buttons == ()
        assert contract.apis == ()
        assert contract.context.field_policies == ()

        # 关键：`data_scope is None` 表示"无任何有效策略"，消费方必须按全拒处理。
        assert contract.context.data_scope is None
        assert contract.context.is_super_admin is False
        assert contract.context.effective_role_ids == frozenset()

    async def test_default_build_still_fails_closed_for_role_less_user(self, db_session) -> None:
        """**默认**行为未被放宽：`build()` 仍然 fail-closed 抛错。

        这是本 Phase 最重要的一条回归：为了让契约可渲染，只在契约服务里
        显式传 `allow_empty_roles=True`；任何其他调用方（判权、预览）
        得到的仍然是"无角色 = 抛错"，不可能静默退化成放行。
        """
        from app.services.effective_permission import EffectivePermissionService

        await _seed(db_session)
        with pytest.raises(ValueError, match="无任何角色范围配置"):
            await EffectivePermissionService(db_session).build(user_id=ROLE_LESS_USER_ID)
