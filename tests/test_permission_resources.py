"""权限资源测试（Phase 3 / DD-20 已冻结）。

覆盖点
-----
- **形状约束的方向性**（unit）：这是最容易写反、且写反后"看起来仍生效"的
  约束，因此单测直接断言生成 SQL 的极性；
- 数据库 CHECK 对五类资源形状的接受与拒绝（integration，真实 PostgreSQL）；
- `(resource_type, resource_code)` 逻辑删除感知唯一；
- 资源 CRUD、父子类型校验、引用拒绝、Menu→Page 多对多、树构造的环路安全；
- 越权拒绝必须留 FAILURE 审计。

不覆盖（属其他 Phase）
-------------------
- HTTP 端点（Phase 8）；`/auth/permissions` 输出（Phase 8）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import AuditAction
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.scope import DataScope
from app.models import (
    MenuPage,
    PermissionResource,
    PermissionResourceType,
    PermissionStatus,
)
from app.models.enums import FieldAccessLevel, most_permissive_field_level
from app.models.permission import (
    PERMISSION_RESOURCE_TYPE_SHAPE_CHECK,
    SHAPE_CLAUSE_SEPARATOR,
)
from app.services.permission_resource import PermissionResourceService
from tests.factories import (
    link_menu_page,
    link_role_field_permission,
    link_role_permission,
    make_permission_resource,
    make_role,
)

ROOT = CurrentActor.super_admin(user_id=9001, username="root")
ADMIN = CurrentActor(
    user_id=9002,
    username="dept-admin",
    role_codes=frozenset({"DEPT_ADMIN"}),
    data_scope=DataScope.DEPARTMENT_CHILDREN,
    department_id=1,
)


# ===========================================================================
# Unit：形状约束的方向
# ===========================================================================
class TestShapeCheckExpression:
    """钉住"类型 ↔ 专属列"约束的极性。"""

    def test_clauses_are_conjoined_by_and(self) -> None:
        """子句之间必须是 `AND`，不能是 `OR`。

        每条子句都是蕴含式 `resource_type <> 'T' OR (T 的列形状)`，
        对"不属于 T 的行"恒真。若用 `OR` 连接，任意一行只要存在一个
        与本行类型不同的 `T`（五类资源里必然存在），对应子句即恒真，
        整条约束随之恒真 —— 形状校验**完全失效**，而且**任何数据都不报错**。

        这不是假想风险：本约束的第一版就是 `OR` 连接的，
        当时单测按 `OR` 切分子句、只校验了子句内部极性，因此放过了它；
        最终由下面的数据库拒绝用例（`TestResourceShapeConstraints`）暴露。
        所以这里同时断言"连接符是 AND"与"切分后子句数量完整"。
        """
        assert SHAPE_CLAUSE_SEPARATOR.strip() == "AND"
        assert " OR (resource_type" not in PERMISSION_RESOURCE_TYPE_SHAPE_CHECK
        clauses = PERMISSION_RESOURCE_TYPE_SHAPE_CHECK.split(SHAPE_CLAUSE_SEPARATOR)
        assert len(clauses) == len(PermissionResourceType)

    def test_each_clause_is_positive_polarity(self) -> None:
        """必然形式必须是 `resource_type <> 'T' OR (列约束)`。

        若写成 `resource_type <> 'T' AND (...)`，语义会反转成
        "**不是** T 的行必须满足 T 的列形状"，与意图完全相反。
        这种反向约束在"库里的数据恰好都是 T"时不会报错，
        属于"看起来生效、实际没保护"的缺陷，所以必须显式钉住。
        """
        clauses = PERMISSION_RESOURCE_TYPE_SHAPE_CHECK.split(SHAPE_CLAUSE_SEPARATOR)
        assert len(clauses) == len(PermissionResourceType)
        for clause, resource_type in zip(clauses, PermissionResourceType, strict=True):
            assert clause.startswith(f"(resource_type <> '{resource_type.value}' OR (")
            assert f"resource_type <> '{resource_type.value}' AND" not in clause

    def test_page_requires_route_and_component(self) -> None:
        clause = PERMISSION_RESOURCE_TYPE_SHAPE_CHECK.split(SHAPE_CLAUSE_SEPARATOR)[0]
        assert "route_path IS NOT NULL" in clause
        assert "component_path IS NOT NULL" in clause
        assert "api_path IS NULL" in clause

    def test_menu_allows_parent_and_icon(self) -> None:
        """MENU 可嵌套、可配图标 —— 两者都**不得**出现在 IS NULL 断言里。

        这是实际发生过的缺陷：早期版本把 `icon` 误放进"必须为 NULL"集合，
        导致菜单无法配置图标。
        """
        clause = next(
            item
            for item in PERMISSION_RESOURCE_TYPE_SHAPE_CHECK.split(SHAPE_CLAUSE_SEPARATOR)
            if "'MENU'" in item
        )
        assert "parent_id IS" not in clause
        assert "icon IS" not in clause

    def test_button_requires_parent(self) -> None:
        clause = next(
            item
            for item in PERMISSION_RESOURCE_TYPE_SHAPE_CHECK.split(SHAPE_CLAUSE_SEPARATOR)
            if "'BUTTON'" in item
        )
        assert "parent_id IS NOT NULL" in clause


class TestFieldLevelMerge:
    """DD-06：多角色字段等级取最宽松者胜。"""

    def test_empty_returns_none(self) -> None:
        assert most_permissive_field_level([]) is None

    @pytest.mark.parametrize(
        ("levels", "expected"),
        [
            ([FieldAccessLevel.HIDDEN, FieldAccessLevel.VISIBLE], FieldAccessLevel.VISIBLE),
            ([FieldAccessLevel.READ_ONLY, FieldAccessLevel.EDITABLE], FieldAccessLevel.EDITABLE),
            ([FieldAccessLevel.HIDDEN, FieldAccessLevel.READ_ONLY], FieldAccessLevel.READ_ONLY),
            ([FieldAccessLevel.HIDDEN], FieldAccessLevel.HIDDEN),
        ],
    )
    def test_most_permissive_wins(self, levels: list[FieldAccessLevel], expected) -> None:
        assert most_permissive_field_level(levels) is expected

    def test_hidden_does_not_override_visible(self) -> None:
        """DD-06 冻结方向的**显式后果**：HIDDEN 不能否决其他角色的 VISIBLE。

        这不是缺陷而是已裁定的语义（与 `00 §1#2` 并集同向）。
        若业务后续要求"HIDDEN 一票否决"，必须重新裁定并改此测试。
        """
        assert (
            most_permissive_field_level([FieldAccessLevel.HIDDEN, FieldAccessLevel.VISIBLE])
            is FieldAccessLevel.VISIBLE
        )


# ===========================================================================
# Integration：数据库约束
# ===========================================================================
async def _assert_db_rejects(session, **kwargs) -> None:  # type: ignore[no-untyped-def]
    """断言数据库拒绝该行（用 SAVEPOINT 隔离，避免污染外层事务）。

    外层事务由 `db_session` 夹具持有并在用例结束回滚，因此这里不能
    直接 `rollback()`（会连带丢掉本用例此前已写入的数据）。
    用 `begin_nested()` 开 SAVEPOINT：失败只回滚到保存点。
    """
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await make_permission_resource(session, **kwargs)
    # SAVEPOINT 回滚后，失败对象仍残留在 session.new 中，
    # 会被后续 flush 再次提交。必须显式丢弃，否则该行可能在
    # 断言之后被意外写入，让"已拒绝"的结论变假。
    for pending in list(session.new):
        session.expunge(pending)


@pytest.mark.integration
class TestResourceShapeConstraints:
    async def test_page_with_route_and_component_is_accepted(self, db_session) -> None:
        resource = await make_permission_resource(
            db_session,
            resource_id=101,
            resource_type=PermissionResourceType.PAGE,
            resource_code="user:list",
            route_path="/users",
            component_path="views/users/index",
        )
        assert resource.route_path == "/users"

    async def test_page_without_route_is_rejected(self, db_session) -> None:
        await _assert_db_rejects(
            db_session,
            resource_id=102,
            resource_type=PermissionResourceType.PAGE,
            resource_code="bad:page",
            component_path="views/x",
        )

    async def test_page_carrying_api_columns_is_rejected(self, db_session) -> None:
        """形状错误必须被拒绝：给 PAGE 塞 api_path 说明调用方理解有误。"""
        await _assert_db_rejects(
            db_session,
            resource_id=103,
            resource_type=PermissionResourceType.PAGE,
            resource_code="bad:page2",
            route_path="/x",
            component_path="views/x",
            api_path="/api/v1/admin/x",
            api_method="GET",
        )

    async def test_menu_with_parent_and_icon_is_accepted(self, db_session) -> None:
        await make_permission_resource(
            db_session,
            resource_id=110,
            resource_type=PermissionResourceType.MENU,
            resource_code="sys",
            icon="setting",
        )
        await make_permission_resource(
            db_session,
            resource_id=111,
            resource_type=PermissionResourceType.MENU,
            resource_code="sys.user",
            parent_id=110,
            icon="user",
        )
        children = await db_session.execute(
            select(PermissionResource.id).where(PermissionResource.parent_id == 110)
        )
        assert set(children.scalars().all()) == {111}

    async def test_button_without_parent_is_rejected(self, db_session) -> None:
        await _assert_db_rejects(
            db_session,
            resource_id=120,
            resource_type=PermissionResourceType.BUTTON,
            resource_code="user:create",
        )

    async def test_self_parent_is_rejected(self, db_session) -> None:
        await _assert_db_rejects(
            db_session,
            resource_id=121,
            resource_type=PermissionResourceType.MENU,
            resource_code="self",
            parent_id=121,
        )

    async def test_api_requires_method_and_path(self, db_session) -> None:
        await _assert_db_rejects(
            db_session,
            resource_id=130,
            resource_type=PermissionResourceType.API,
            resource_code="api:missing",
        )

    async def test_api_method_domain_is_enforced(self, db_session) -> None:
        await _assert_db_rejects(
            db_session,
            resource_id=131,
            resource_type=PermissionResourceType.API,
            resource_code="api:badmethod",
            api_method="FETCH",
            api_path="/api/v1/admin/x",
        )

    async def test_field_requires_owner_and_key(self, db_session) -> None:
        await _assert_db_rejects(
            db_session,
            resource_id=140,
            resource_type=PermissionResourceType.FIELD,
            resource_code="user.phone",
            field_key="phone",
        )


@pytest.mark.integration
class TestResourceUniqueness:
    async def test_code_unique_within_type(self, db_session) -> None:
        await make_permission_resource(
            db_session,
            resource_id=201,
            resource_type=PermissionResourceType.PAGE,
            resource_code="dup",
            route_path="/a",
            component_path="a",
        )
        await _assert_db_rejects(
            db_session,
            resource_id=202,
            resource_type=PermissionResourceType.PAGE,
            resource_code="dup",
            route_path="/b",
            component_path="b",
        )

    async def test_same_code_allowed_across_types(self, db_session) -> None:
        """DD-20 冻结"按类型唯一"：PAGE 与 BUTTON 可同名。"""
        await make_permission_resource(
            db_session,
            resource_id=210,
            resource_type=PermissionResourceType.PAGE,
            resource_code="user:list",
            route_path="/users",
            component_path="views/users",
        )
        await make_permission_resource(
            db_session,
            resource_id=211,
            resource_type=PermissionResourceType.PAGE,
            resource_code="user:manage",
            route_path="/users/manage",
            component_path="views/users/manage",
        )
        button = await make_permission_resource(
            db_session,
            resource_id=212,
            resource_type=PermissionResourceType.BUTTON,
            resource_code="user:list",
            parent_id=210,
        )
        assert button.resource_code == "user:list"

    async def test_soft_deleted_code_can_be_reused(self, db_session) -> None:
        """Spec 00 §6：唯一约束必须考虑逻辑删除后的重建。"""
        from app.db.base import utc_now

        first = await make_permission_resource(
            db_session,
            resource_id=220,
            resource_type=PermissionResourceType.PAGE,
            resource_code="reuse",
            route_path="/r",
            component_path="r",
        )
        first.deleted_at = utc_now()
        await db_session.flush()

        again = await make_permission_resource(
            db_session,
            resource_id=221,
            resource_type=PermissionResourceType.PAGE,
            resource_code="reuse",
            route_path="/r2",
            component_path="r2",
        )
        assert again.id == 221


# ===========================================================================
# Integration：Service 行为
# ===========================================================================
@pytest.mark.integration
class TestResourceServiceCreate:
    async def test_super_admin_can_create(self, db_session, audit_recorder) -> None:
        service = PermissionResourceService(db_session, audit=audit_recorder)
        resource = await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.PAGE,
            resource_code="role:list",
            resource_name="角色列表",
            route_path="/roles",
            component_path="views/roles/index",
        )
        assert resource.resource_code == "role:list"
        event = audit_recorder.find(str(AuditAction.PERMISSION_RESOURCE_CREATE))
        assert event is not None
        assert event.after_data["resource_code"] == "role:list"

    async def test_non_super_admin_is_denied_and_audited(self, db_session, audit_recorder) -> None:
        service = PermissionResourceService(db_session, audit=audit_recorder)
        with pytest.raises(PermissionDeniedError):
            await service.create(
                actor=ADMIN,
                resource_type=PermissionResourceType.PAGE,
                resource_code="x",
                resource_name="x",
                route_path="/x",
                component_path="x",
            )
        failures = audit_recorder.failures()
        assert len(failures) == 1
        assert str(failures[0].action) == str(AuditAction.PERMISSION_RESOURCE_CREATE)

    async def test_duplicate_code_conflicts(self, db_session) -> None:
        service = PermissionResourceService(db_session)
        await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.PAGE,
            resource_code="dup2",
            resource_name="dup2",
            route_path="/d",
            component_path="d",
        )
        with pytest.raises(ConflictError):
            await service.create(
                actor=ROOT,
                resource_type=PermissionResourceType.PAGE,
                resource_code="dup2",
                resource_name="dup2",
                route_path="/d2",
                component_path="d2",
            )

    async def test_button_parent_must_be_page(self, db_session) -> None:
        service = PermissionResourceService(db_session)
        menu = await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.MENU,
            resource_code="m1",
            resource_name="M1",
        )
        with pytest.raises(BadRequestError, match="父资源必须是 PAGE"):
            await service.create(
                actor=ROOT,
                resource_type=PermissionResourceType.BUTTON,
                resource_code="b1",
                resource_name="B1",
                parent_id=menu.id,
            )

    async def test_shape_violation_returns_400_not_500(self, db_session) -> None:
        """应用层形状校验必须给出 400，而不是让数据库抛 500。"""
        service = PermissionResourceService(db_session)
        with pytest.raises(BadRequestError, match="必须提供 route_path"):
            await service.create(
                actor=ROOT,
                resource_type=PermissionResourceType.PAGE,
                resource_code="p-bad",
                resource_name="P",
                component_path="c",
            )

    async def test_api_path_must_start_with_slash(self, db_session) -> None:
        service = PermissionResourceService(db_session)
        with pytest.raises(BadRequestError, match="api_path"):
            await service.create(
                actor=ROOT,
                resource_type=PermissionResourceType.API,
                resource_code="api1",
                resource_name="API1",
                api_method="GET",
                api_path="api/v1/admin/x",
            )

    async def test_field_owner_must_be_page(self, db_session) -> None:
        service = PermissionResourceService(db_session)
        await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.PAGE,
            resource_code="user:list",
            resource_name="用户列表",
            route_path="/users",
            component_path="views/users",
        )
        menu = await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.MENU,
            resource_code="menu1",
            resource_name="菜单1",
        )
        with pytest.raises(BadRequestError, match="归属资源必须是 PAGE"):
            await service.create(
                actor=ROOT,
                resource_type=PermissionResourceType.FIELD,
                resource_code="user.phone",
                resource_name="手机号",
                field_key="phone",
                owner_resource_id=menu.id,
            )

    async def test_duplicate_field_key_in_same_page_conflicts(self, db_session) -> None:
        service = PermissionResourceService(db_session)
        page = await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.PAGE,
            resource_code="user:list",
            resource_name="用户列表",
            route_path="/users",
            component_path="views/users",
        )
        await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.FIELD,
            resource_code="user.phone",
            resource_name="手机号",
            field_key="phone",
            owner_resource_id=page.id,
        )
        with pytest.raises(ConflictError, match="同名字段"):
            await service.create(
                actor=ROOT,
                resource_type=PermissionResourceType.FIELD,
                resource_code="user.phone2",
                resource_name="手机号2",
                field_key="phone",
                owner_resource_id=page.id,
            )


@pytest.mark.integration
class TestResourceServiceUpdateAndDelete:
    async def _make_page(self, session, *, resource_id: int = 301):  # type: ignore[no-untyped-def]
        return await make_permission_resource(
            session,
            resource_id=resource_id,
            resource_type=PermissionResourceType.PAGE,
            resource_code=f"page:{resource_id}",
            route_path="/p",
            component_path="p",
        )

    async def test_update_name_and_status(self, db_session, audit_recorder) -> None:
        page = await self._make_page(db_session)
        service = PermissionResourceService(db_session, audit=audit_recorder)
        updated = await service.update(
            actor=ROOT,
            resource_id=page.id,
            resource_name="新名称",
            status=PermissionStatus.DISABLED,
        )
        assert updated.resource_name == "新名称"
        assert updated.status is PermissionStatus.DISABLED
        event = audit_recorder.find(str(AuditAction.PERMISSION_RESOURCE_UPDATE))
        assert event is not None
        assert event.before_data["resource_name"] != event.after_data["resource_name"]

    async def test_update_cannot_blank_required_column(self, db_session) -> None:
        """把 PAGE 的路由置空必须被拒绝（否则前端拿到无法跳转的页面）。"""
        page = await self._make_page(db_session, resource_id=302)
        service = PermissionResourceService(db_session)
        with pytest.raises(BadRequestError):
            # route_path 不在 update 的可改字段里，用 shape 校验验证一致性：
            # 直接改模型再调用 update 的其他字段以触发形状校验
            page.route_path = None
            await service.update(actor=ROOT, resource_id=page.id, resource_name="x")

    async def test_delete_refused_when_authorized_to_role(self, db_session) -> None:
        page = await self._make_page(db_session, resource_id=310)
        role = await make_role(db_session, role_id=3100, role_code="R310")
        await link_role_permission(db_session, role_id=role.id, resource_id=page.id)

        service = PermissionResourceService(db_session)
        with pytest.raises(ConflictError, match="角色授权"):
            await service.delete(actor=ROOT, resource_id=page.id)

    async def test_delete_failure_is_audited(self, db_session, audit_recorder) -> None:
        page = await self._make_page(db_session, resource_id=311)
        role = await make_role(db_session, role_id=3101, role_code="R311")
        await link_role_field_permission(
            db_session, role_id=role.id, field_id=page.id, access_level=FieldAccessLevel.VISIBLE
        )
        service = PermissionResourceService(db_session, audit=audit_recorder)
        with pytest.raises(ConflictError):
            await service.delete(actor=ROOT, resource_id=page.id)
        failures = audit_recorder.failures()
        assert len(failures) == 1
        assert str(failures[0].action) == str(AuditAction.PERMISSION_RESOURCE_DELETE)

    async def test_delete_refused_when_child_exists(self, db_session) -> None:
        page = await self._make_page(db_session, resource_id=320)
        await make_permission_resource(
            db_session,
            resource_id=321,
            resource_type=PermissionResourceType.BUTTON,
            resource_code="btn",
            parent_id=page.id,
        )
        service = PermissionResourceService(db_session)
        with pytest.raises(ConflictError, match="子资源"):
            await service.delete(actor=ROOT, resource_id=page.id)

    async def test_delete_refused_when_menu_page_linked(self, db_session) -> None:
        menu = await make_permission_resource(
            db_session,
            resource_id=330,
            resource_type=PermissionResourceType.MENU,
            resource_code="menux",
        )
        page = await self._make_page(db_session, resource_id=331)
        await link_menu_page(db_session, menu_id=menu.id, page_id=page.id)
        service = PermissionResourceService(db_session)
        with pytest.raises(ConflictError, match="菜单-页面关联"):
            await service.delete(actor=ROOT, resource_id=page.id)

    async def test_delete_soft_deletes_and_disables(self, db_session) -> None:
        page = await self._make_page(db_session, resource_id=340)
        service = PermissionResourceService(db_session)
        deleted = await service.delete(actor=ROOT, resource_id=page.id)
        assert deleted.deleted_at is not None
        assert deleted.status is PermissionStatus.DISABLED
        with pytest.raises(NotFoundError):
            await service.get(actor=ROOT, resource_id=page.id)


@pytest.mark.integration
class TestMenuPages:
    async def test_replace_and_clear(self, db_session, audit_recorder) -> None:
        service = PermissionResourceService(db_session, audit=audit_recorder)
        menu = await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.MENU,
            resource_code="nav",
            resource_name="导航",
        )
        pages = [
            await service.create(
                actor=ROOT,
                resource_type=PermissionResourceType.PAGE,
                resource_code=f"nav.page{index}",
                resource_name=f"页面{index}",
                route_path=f"/n{index}",
                component_path=f"n{index}",
            )
            for index in range(3)
        ]

        before, after = await service.set_menu_pages(
            actor=ROOT, menu_id=menu.id, page_ids=frozenset({pages[0].id, pages[1].id})
        )
        assert before == frozenset()
        assert after == frozenset({pages[0].id, pages[1].id})

        listed = await service.list_menu_pages(actor=ROOT, menu_id=menu.id)
        assert {page.id for page in listed} == {pages[0].id, pages[1].id}

        # 整体替换：第二次只留 pages[2]
        await service.set_menu_pages(actor=ROOT, menu_id=menu.id, page_ids=frozenset({pages[2].id}))
        rows = (
            (await db_session.execute(select(MenuPage.page_id).where(MenuPage.menu_id == menu.id)))
            .scalars()
            .all()
        )
        assert set(rows) == {pages[2].id}

    async def test_non_page_target_is_rejected(self, db_session) -> None:
        service = PermissionResourceService(db_session)
        menu = await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.MENU,
            resource_code="nav2",
            resource_name="导航2",
        )
        other_menu = await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.MENU,
            resource_code="nav3",
            resource_name="导航3",
        )
        with pytest.raises(BadRequestError, match="不是 PAGE 类型"):
            await service.set_menu_pages(
                actor=ROOT, menu_id=menu.id, page_ids=frozenset({other_menu.id})
            )

    async def test_only_menu_can_link_pages(self, db_session) -> None:
        service = PermissionResourceService(db_session)
        page = await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.PAGE,
            resource_code="solo",
            resource_name="单页",
            route_path="/solo",
            component_path="solo",
        )
        with pytest.raises(BadRequestError, match="只有 MENU"):
            await service.list_menu_pages(actor=ROOT, menu_id=page.id)


@pytest.mark.integration
class TestResourceTree:
    async def test_tree_nests_children(self, db_session) -> None:
        service = PermissionResourceService(db_session)
        root = await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.MENU,
            resource_code="t.root",
            resource_name="根",
        )
        child = await service.create(
            actor=ROOT,
            resource_type=PermissionResourceType.MENU,
            resource_code="t.child",
            resource_name="子",
            parent_id=root.id,
        )
        nodes = await service.tree(actor=ROOT, resource_type=PermissionResourceType.MENU)
        assert len(nodes) == 1
        assert nodes[0].resource.id == root.id
        assert len(nodes[0].children) == 1
        assert nodes[0].children[0].resource.id == child.id

    async def test_tree_terminates_on_data_cycle(self, db_session) -> None:
        """即使库里被直接写入环，构树也必须终止且不丢节点。

        服务层会拒绝成环，所以这里**绕过服务直接写库**：
        这正是"最后一道防线"要覆盖的场景。

        为什么必须分"先建节点、后改父指针"两步
        ------------------------------------
        外键只保证"被引用的行存在"，**不保证无环**。
        直接插入 `401.parent_id = 402` 会被拒绝，但那是因为 `402` 尚不存在
        （引用完整性问题），而不是因为环被禁止；
        先建好两个节点、再把 `401` 的父指针改成 `402`，环就成立了。
        这说明"数据库能拦住环"是错误认知 —— 读路径必须自行保证收敛。
        """
        first = await make_permission_resource(
            db_session,
            resource_id=401,
            resource_type=PermissionResourceType.MENU,
            resource_code="cyc.a",
        )
        await make_permission_resource(
            db_session,
            resource_id=402,
            resource_type=PermissionResourceType.MENU,
            resource_code="cyc.b",
            parent_id=401,
        )
        # 此时 401 ← 402 已存在；把 401 的父指向 402 即形成 401 ⇄ 402 环。
        first.parent_id = 402
        await db_session.flush()

        service = PermissionResourceService(db_session)
        nodes = await service.tree(actor=ROOT, resource_type=PermissionResourceType.MENU)
        seen: set[int] = set()

        def collect(node) -> None:  # type: ignore[no-untyped-def]
            assert node.resource.id not in seen, "构树出现重复节点（环未收敛）"
            seen.add(node.resource.id)
            for child in node.children:
                collect(child)

        for node in nodes:
            collect(node)
        # 环内两个节点都必须出现（不允许因为无法到达根而被静默丢弃）。
        assert seen == {401, 402}
