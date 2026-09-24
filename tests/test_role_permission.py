"""角色权限授予测试（Task 3.6~3.9 / DD-20、DD-06 已冻结）。

覆盖点
-----
- **按类型隔离的整体替换**（本文件最重要的用例）：
  `PUT /roles/{id}/permissions/pages` 绝不能连带清掉该角色的 API / BUTTON 授权。
  若实现成"先清空该角色全部授权再写入"，一次改页面权限就会静默删除接口权限 ——
  产品事故级行为，且因为结果是"权限变小"而不容易被立刻发现。
- 被授权资源必须**存在、有效（未删除 + ACTIVE）、且类型正确**；
  类型不校验会让"配了却没生效"这种配置失效极难排查。
- 字段权限携带四级取值（DD-06）；
- 每次真实替换必须递增权限版本（Spec `11 §2`）；
- 授权拒绝留 FAILURE 审计。

不覆盖（属其他 Phase / 其他模块）
------------------------------
- 多角色字段等级合并 → `tests/test_effective_permission.py`；
- 资源定义 CRUD → `tests/test_permission_resources.py`；
- HTTP 端点（Phase 8）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.audit import AuditAction
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, NotFoundError, PermissionDeniedError
from app.core.scope import DataScope
from app.db.base import utc_now
from app.models import (
    FieldAccessLevel,
    PermissionResource,
    PermissionResourceType,
    PermissionStatus,
    RolePermission,
)
from app.repositories.permission import PermissionVersionRepository
from app.services.role_permission import RolePermissionService
from tests.factories import (
    link_role_permission,
    make_permission_resource,
    make_role,
)

pytestmark = pytest.mark.integration

ROLE_ID = 2001
PAGE_A = 2010
PAGE_B = 2020
API_A = 2030
BUTTON_A = 2040
FIELD_A = 2050
FIELD_B = 2060

ROOT = CurrentActor.super_admin(user_id=9001, username="root")
ADMIN = CurrentActor(
    user_id=9002,
    username="dept-admin",
    role_codes=frozenset({"DEPT_ADMIN"}),
    data_scope=DataScope.DEPARTMENT_CHILDREN,
    department_id=1,
)


async def _seed(session) -> None:
    """建立一个角色与覆盖全部五类的资源。"""
    await make_role(session, role_id=ROLE_ID, role_code="GRANTED")
    await make_permission_resource(
        session,
        resource_id=PAGE_A,
        resource_type=PermissionResourceType.PAGE,
        resource_code="page:a",
        route_path="/a",
        component_path="a",
    )
    await make_permission_resource(
        session,
        resource_id=PAGE_B,
        resource_type=PermissionResourceType.PAGE,
        resource_code="page:b",
        route_path="/b",
        component_path="b",
    )
    await make_permission_resource(
        session,
        resource_id=API_A,
        resource_type=PermissionResourceType.API,
        resource_code="api:a",
        api_method="GET",
        api_path="/api/v1/admin/a",
    )
    await make_permission_resource(
        session,
        resource_id=BUTTON_A,
        resource_type=PermissionResourceType.BUTTON,
        resource_code="btn:a",
        parent_id=PAGE_A,
    )
    await make_permission_resource(
        session,
        resource_id=FIELD_A,
        resource_type=PermissionResourceType.FIELD,
        resource_code="page.phone",
        field_key="phone",
        owner_resource_id=PAGE_A,
    )
    await make_permission_resource(
        session,
        resource_id=FIELD_B,
        resource_type=PermissionResourceType.FIELD,
        resource_code="page.email",
        field_key="email",
        owner_resource_id=PAGE_A,
    )


async def _version(session) -> int:
    return await PermissionVersionRepository(session).get()


async def _grant_count(session, *, role_id: int = ROLE_ID) -> int:
    stmt = select(func.count()).select_from(RolePermission).where(RolePermission.role_id == role_id)
    return int((await session.execute(stmt)).scalar_one())


# ===========================================================================
# 按类型隔离（关键回归面）
# ===========================================================================
class TestTypeScopedReplacement:
    async def test_replacing_pages_does_not_touch_apis_or_buttons(self, db_session) -> None:
        await _seed(db_session)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=PAGE_A)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=API_A)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=BUTTON_A)

        service = RolePermissionService(db_session)
        view = await service.replace(
            actor=ROOT, role_id=ROLE_ID, kind="pages", resource_ids=frozenset({PAGE_B})
        )

        assert view.page_ids == frozenset({PAGE_B})
        # 这两条是本用例的全部意义所在：
        assert view.api_ids == frozenset({API_A}), "改页面权限不得连带清除 API 授权"
        assert view.button_ids == frozenset({BUTTON_A}), "改页面权限不得连带清除按钮授权"

    async def test_replacing_with_empty_set_clears_only_that_type(self, db_session) -> None:
        await _seed(db_session)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=PAGE_A)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=API_A)

        service = RolePermissionService(db_session)
        view = await service.replace(
            actor=ROOT, role_id=ROLE_ID, kind="pages", resource_ids=frozenset()
        )

        assert view.page_ids == frozenset()
        assert view.api_ids == frozenset({API_A})

    async def test_each_kind_is_independent(self, db_session) -> None:
        """四个类别各自替换后互不影响 —— 参数化覆盖全部类别组合。"""
        await _seed(db_session)
        service = RolePermissionService(db_session)

        await service.replace(
            actor=ROOT, role_id=ROLE_ID, kind="pages", resource_ids=frozenset({PAGE_A})
        )
        await service.replace(
            actor=ROOT, role_id=ROLE_ID, kind="apis", resource_ids=frozenset({API_A})
        )
        await service.replace(
            actor=ROOT, role_id=ROLE_ID, kind="buttons", resource_ids=frozenset({BUTTON_A})
        )

        view = await service.replace(
            actor=ROOT, role_id=ROLE_ID, kind="pages", resource_ids=frozenset()
        )
        assert view.page_ids == frozenset()
        assert view.api_ids == frozenset({API_A})
        assert view.button_ids == frozenset({BUTTON_A})

    async def test_replacement_is_idempotent(self, db_session) -> None:
        """重复提交同一请求不得产生重复行（复合主键 + 差异写入共同保证）。"""
        await _seed(db_session)
        service = RolePermissionService(db_session)
        target = frozenset({PAGE_A, PAGE_B})

        await service.replace(actor=ROOT, role_id=ROLE_ID, kind="pages", resource_ids=target)
        after_first = await _grant_count(db_session)
        view = await service.replace(actor=ROOT, role_id=ROLE_ID, kind="pages", resource_ids=target)

        assert view.page_ids == target
        assert await _grant_count(db_session) == after_first == 2

    async def test_unknown_kind_returns_400(self, db_session) -> None:
        await _seed(db_session)
        service = RolePermissionService(db_session)
        with pytest.raises(BadRequestError, match="不支持的权限类别"):
            await service.replace(
                actor=ROOT, role_id=ROLE_ID, kind="fields", resource_ids=frozenset()
            )


# ===========================================================================
# 被授权资源的校验
# ===========================================================================
class TestAssignableResourceValidation:
    async def test_wrong_type_is_rejected(self, db_session) -> None:
        """把 PAGE 的 ID 传给 apis 会让资源落库但判权时被按类型过滤掉
        —— "配了却没生效"，且几乎无法从界面看出原因。必须在此拦住。"""
        await _seed(db_session)
        service = RolePermissionService(db_session)
        with pytest.raises(BadRequestError, match="不是 API 类型"):
            await service.replace(
                actor=ROOT, role_id=ROLE_ID, kind="apis", resource_ids=frozenset({PAGE_A})
            )

    async def test_missing_resource_is_rejected(self, db_session) -> None:
        await _seed(db_session)
        service = RolePermissionService(db_session)
        with pytest.raises(BadRequestError, match="不存在"):
            await service.replace(
                actor=ROOT,
                role_id=ROLE_ID,
                kind="pages",
                resource_ids=frozenset({PAGE_A, 999_999}),
            )

    async def test_disabled_resource_is_rejected(self, db_session) -> None:
        """DISABLED 资源不参与有效权限计算 —— 允许授权等于"配了没生效"。"""
        await _seed(db_session)
        resource = (
            await db_session.execute(
                select(PermissionResource).where(PermissionResource.id == PAGE_B)
            )
        ).scalar_one()
        resource.status = PermissionStatus.DISABLED
        await db_session.flush()

        service = RolePermissionService(db_session)
        with pytest.raises(BadRequestError, match="不存在"):
            await service.replace(
                actor=ROOT, role_id=ROLE_ID, kind="pages", resource_ids=frozenset({PAGE_B})
            )

    async def test_soft_deleted_resource_is_rejected(self, db_session) -> None:
        await _seed(db_session)
        resource = (
            await db_session.execute(
                select(PermissionResource).where(PermissionResource.id == PAGE_B)
            )
        ).scalar_one()
        resource.deleted_at = utc_now()
        await db_session.flush()

        service = RolePermissionService(db_session)
        with pytest.raises(BadRequestError, match="不存在"):
            await service.replace(
                actor=ROOT, role_id=ROLE_ID, kind="pages", resource_ids=frozenset({PAGE_B})
            )

    async def test_missing_role_returns_404(self, db_session) -> None:
        await _seed(db_session)
        service = RolePermissionService(db_session)
        with pytest.raises(NotFoundError, match="角色不存在"):
            await service.replace(
                actor=ROOT, role_id=999_999, kind="pages", resource_ids=frozenset({PAGE_A})
            )


# ===========================================================================
# 字段权限（DD-06）
# ===========================================================================
class TestFieldPermissions:
    async def test_replace_sets_levels(self, db_session) -> None:
        await _seed(db_session)
        service = RolePermissionService(db_session)
        view = await service.replace_fields(
            actor=ROOT,
            role_id=ROLE_ID,
            levels={FIELD_A: FieldAccessLevel.VISIBLE, FIELD_B: FieldAccessLevel.HIDDEN},
        )
        assert view.field_levels == {
            FIELD_A: FieldAccessLevel.VISIBLE,
            FIELD_B: FieldAccessLevel.HIDDEN,
        }

    async def test_replace_fields_is_idempotent_and_updates_level(self, db_session) -> None:
        await _seed(db_session)
        service = RolePermissionService(db_session)
        await service.replace_fields(
            actor=ROOT, role_id=ROLE_ID, levels={FIELD_A: FieldAccessLevel.VISIBLE}
        )
        view = await service.replace_fields(
            actor=ROOT, role_id=ROLE_ID, levels={FIELD_A: FieldAccessLevel.EDITABLE}
        )
        assert view.field_levels == {FIELD_A: FieldAccessLevel.EDITABLE}

    async def test_replace_fields_merges_with_binary_grants(self, db_session) -> None:
        """字段权限走独立表；替换它不得影响二元授权。"""
        await _seed(db_session)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=PAGE_A)

        service = RolePermissionService(db_session)
        view = await service.replace_fields(
            actor=ROOT, role_id=ROLE_ID, levels={FIELD_A: FieldAccessLevel.READ_ONLY}
        )
        assert view.page_ids == frozenset({PAGE_A})
        assert view.field_levels == {FIELD_A: FieldAccessLevel.READ_ONLY}

    async def test_non_field_target_is_rejected(self, db_session) -> None:
        await _seed(db_session)
        service = RolePermissionService(db_session)
        with pytest.raises(BadRequestError, match="不是 FIELD 类型"):
            await service.replace_fields(
                actor=ROOT, role_id=ROLE_ID, levels={PAGE_A: FieldAccessLevel.VISIBLE}
            )

    async def test_missing_field_target_is_rejected(self, db_session) -> None:
        await _seed(db_session)
        service = RolePermissionService(db_session)
        with pytest.raises(BadRequestError, match="不存在"):
            await service.replace_fields(
                actor=ROOT, role_id=ROLE_ID, levels={999_999: FieldAccessLevel.VISIBLE}
            )

    async def test_empty_levels_clears_all_fields(self, db_session) -> None:
        await _seed(db_session)
        service = RolePermissionService(db_session)
        await service.replace_fields(
            actor=ROOT, role_id=ROLE_ID, levels={FIELD_A: FieldAccessLevel.VISIBLE}
        )
        view = await service.replace_fields(actor=ROOT, role_id=ROLE_ID, levels={})
        assert view.field_levels == {}


# ===========================================================================
# 查询与审计
# ===========================================================================
class TestViewAndAudit:
    async def test_get_returns_all_five_categories(self, db_session, audit_recorder) -> None:
        await _seed(db_session)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=PAGE_A)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=API_A)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=BUTTON_A)

        service = RolePermissionService(db_session, audit=audit_recorder)
        view = await service.get(actor=ROOT, role_id=ROLE_ID)

        assert view.page_ids == frozenset({PAGE_A})
        assert view.menu_ids == frozenset()
        assert view.button_ids == frozenset({BUTTON_A})
        assert view.api_ids == frozenset({API_A})
        assert view.field_levels == {}
        assert view.ids_of(PermissionResourceType.PAGE) == frozenset({PAGE_A})
        event = audit_recorder.find(str(AuditAction.ROLE_PERMISSION_READ))
        assert event is not None

    async def test_read_excludes_invalid_resources(self, db_session) -> None:
        """读路径与判权口径一致：无效资源不出现（否则界面会显示"已授权但不生效"）。"""
        await _seed(db_session)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=PAGE_A)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=PAGE_B)

        from app.models import PermissionResource

        resource = (
            await db_session.execute(
                select(PermissionResource).where(PermissionResource.id == PAGE_B)
            )
        ).scalar_one()
        resource.deleted_at = utc_now()
        await db_session.flush()

        service = RolePermissionService(db_session)
        view = await service.get(actor=ROOT, role_id=ROLE_ID)
        assert view.page_ids == frozenset({PAGE_A})

    async def test_replace_bumps_version(self, db_session) -> None:
        await _seed(db_session)
        before = await _version(db_session)
        service = RolePermissionService(db_session)
        await service.replace(
            actor=ROOT, role_id=ROLE_ID, kind="pages", resource_ids=frozenset({PAGE_A})
        )
        assert await _version(db_session) == before + 1

    async def test_replace_fields_bumps_version(self, db_session) -> None:
        await _seed(db_session)
        before = await _version(db_session)
        service = RolePermissionService(db_session)
        await service.replace_fields(
            actor=ROOT, role_id=ROLE_ID, levels={FIELD_A: FieldAccessLevel.VISIBLE}
        )
        assert await _version(db_session) == before + 1

    async def test_replace_audits_before_and_after(self, db_session, audit_recorder) -> None:
        await _seed(db_session)
        service = RolePermissionService(db_session, audit=audit_recorder)
        await service.replace(
            actor=ROOT, role_id=ROLE_ID, kind="pages", resource_ids=frozenset({PAGE_A})
        )
        event = audit_recorder.find(str(AuditAction.ROLE_PERMISSION_UPDATE))
        assert event is not None
        assert event.before_data["resource_ids"] == []
        assert event.after_data["resource_ids"] == [PAGE_A]

    async def test_replace_denied_is_audited(self, db_session, audit_recorder) -> None:
        await _seed(db_session)
        service = RolePermissionService(db_session, audit=audit_recorder)
        with pytest.raises(PermissionDeniedError):
            await service.replace(
                actor=ADMIN, role_id=ROLE_ID, kind="pages", resource_ids=frozenset({PAGE_A})
            )
        failures = audit_recorder.failures()
        assert len(failures) == 1
        assert str(failures[0].action) == str(AuditAction.ROLE_PERMISSION_UPDATE)

    async def test_list_granted_resources_returns_details(self, db_session) -> None:
        """后台界面需要名称 / 路由，因此必须能按类型取资源明细。"""
        await _seed(db_session)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=PAGE_B)
        await link_role_permission(db_session, role_id=ROLE_ID, resource_id=PAGE_A)

        service = RolePermissionService(db_session)
        resources = await service.list_granted_resources(
            actor=ROOT, role_id=ROLE_ID, resource_type=PermissionResourceType.PAGE
        )
        assert [resource.id for resource in resources] == [PAGE_A, PAGE_B]
        assert resources[0].route_path == "/a"
