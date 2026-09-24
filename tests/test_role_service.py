"""角色服务测试（Task 3.3：Role CRUD + 引用检查 + 版本递增）。

覆盖点
-----
- 创建：唯一编码、长度校验、默认数据范围、审计；
- **授权口径已从 Phase 2 的 INTERIM 保守默认切换为 API Permission**
  （DD-20 冻结）：持有 `ROLE_MANAGE` API 权限的非 SUPER_ADMIN **可以**管理角色，
  没有该权限的非 SUPER_ADMIN **不可以**；
- 读取 / 列表（分页参数校验先于授权，避免"用参数错误探测权限"）；
- 修改：`role_code` 不可改（冻结契约）；改状态**必须**递增权限版本，改名称不必；
- 删除：用户持有 / 继承引用 → 409；自己的从属授权与 CUSTOM 行 → 清理；
  逻辑删除 + 禁用 + 版本递增；
- 所有拒绝路径必须留 FAILURE 审计，且**恰好一条**（防重复埋点）。

不覆盖（属其他 Phase / 其他模块的测试）
-----------------------------------
- 数据范围读写 → `tests/test_role_data_scope.py`；
- 权限授予 → `tests/test_role_permission.py`；
- 继承关系 → `tests/test_role_inheritance.py`；
- HTTP 端点（Phase 8）。
"""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import select

from app.audit import AuditAction
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.scope import DataScope
from app.models import FieldAccessLevel, PermissionResourceType, Role, RoleStatus
from app.models.role import RoleCustomScopeDepartment
from app.repositories.permission import PermissionVersionRepository
from app.services.authorization import ApiPermissionCode
from app.services.role import (
    MAX_DESCRIPTION_LENGTH,
    MAX_ROLE_NAME_LENGTH,
    RoleService,
)
from tests.factories import (
    link_role_custom_scope,
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

ROOT = CurrentActor.super_admin(user_id=9001, username="root")
#: 有角色但不是 SUPER_ADMIN —— 用于验证"授权已不再只认 SUPER_ADMIN"
ADMIN = CurrentActor(
    user_id=9002,
    username="dept-admin",
    role_codes=frozenset({"DEPT_ADMIN"}),
    data_scope=DataScope.DEPARTMENT_CHILDREN,
    department_id=1,
)


async def _grant_role_manage_api(session, *, role_id: int, user_id: int) -> None:
    """给角色配上 `ROLE_MANAGE` API 权限，并把角色授予用户。

    这是"非 SUPER_ADMIN 也能管理角色"的必要条件 ——
    授权判定看的是**有效 API 权限集合**，不是身份名称。
    """
    resource = await make_permission_resource(
        session,
        resource_id=role_id + 500_000,
        resource_type=PermissionResourceType.API,
        resource_code=ApiPermissionCode.ROLE_MANAGE.value,
        api_method="POST",
        api_path="/api/v1/admin/roles",
    )
    await link_role_permission(session, role_id=role_id, resource_id=resource.id)
    await link_user_role(session, user_id=user_id, role_id=role_id)


async def _version(session) -> int:
    return await PermissionVersionRepository(session).get()


# ===========================================================================
# 创建
# ===========================================================================
class TestRoleCreate:
    async def test_super_admin_can_create_and_is_audited(self, db_session, audit_recorder) -> None:
        service = RoleService(db_session, audit=audit_recorder)
        role = await service.create(
            actor=ROOT, role_code="AUDITOR", role_name="审计员", description="只读审计"
        )
        assert role.role_code == "AUDITOR"
        assert role.status is RoleStatus.ACTIVE
        event = audit_recorder.find(str(AuditAction.ROLE_CREATE))
        assert event is not None
        assert event.after_data["role_code"] == "AUDITOR"

    async def test_default_data_scope_is_department_children(self, db_session) -> None:
        """Spec 03 §10：未显式配置时使用部门管理员默认值。"""
        service = RoleService(db_session)
        role = await service.create(actor=ROOT, role_code="DEFAULTS", role_name="默认")
        assert role.data_scope is DataScope.DEPARTMENT_CHILDREN

    async def test_create_does_not_bump_permission_version(self, db_session) -> None:
        """新建角色不改变任何人的权限（无用户持有、无授权）→ 不抖动版本。"""
        before = await _version(db_session)
        service = RoleService(db_session)
        await service.create(actor=ROOT, role_code="FRESH", role_name="新建")
        assert await _version(db_session) == before

    async def test_duplicate_code_conflicts(self, db_session) -> None:
        service = RoleService(db_session)
        await service.create(actor=ROOT, role_code="DUP", role_name="一")
        with pytest.raises(ConflictError, match="角色编码已存在"):
            await service.create(actor=ROOT, role_code="DUP", role_name="二")

    async def test_soft_deleted_code_can_be_reused(self, db_session) -> None:
        """Spec 00 §6 / 07 §3：唯一约束考虑逻辑删除。"""
        service = RoleService(db_session)
        first = await service.create(actor=ROOT, role_code="REUSE", role_name="一")
        await service.delete(actor=ROOT, role_id=first.id)
        again = await service.create(actor=ROOT, role_code="REUSE", role_name="二")
        assert again.role_code == "REUSE"

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("role_code", ""),
            ("role_code", "   "),
            ("role_name", ""),
            ("role_code", "X" * 65),
            ("role_name", "X" * (MAX_ROLE_NAME_LENGTH + 1)),
            ("description", "X" * (MAX_DESCRIPTION_LENGTH + 1)),
        ],
    )
    async def test_invalid_text_lengths_return_400(self, db_session, field, value) -> None:
        """长度 / 非空校验必须在应用层给出 400，而不是让数据库报 500。"""
        service = RoleService(db_session)
        payload: dict[str, str] = {"role_code": "OK", "role_name": "OK"}
        payload[field] = value
        with pytest.raises(BadRequestError):
            await service.create(actor=ROOT, **payload)


class TestRoleCreateAuthorization:
    """DD-20 冻结后，角色管理权限来自 API Permission，不再是 INTERIM 的"仅 SUPER_ADMIN"。"""

    async def test_holder_of_role_manage_api_can_create(self, db_session) -> None:
        await make_user(db_session, user_id=9101, username="role-admin")
        await make_role(db_session, role_id=9102, role_code="ROLE_ADMIN")
        await _grant_role_manage_api(db_session, role_id=9102, user_id=9101)

        actor = CurrentActor(user_id=9101, username="role-admin")
        assert actor.is_super_admin is False

        service = RoleService(db_session)
        role = await service.create(actor=actor, role_code="MADE_BY_ADMIN", role_name="管理员建的")
        assert role.role_code == "MADE_BY_ADMIN"

    async def test_non_super_admin_without_permission_is_denied(self, db_session, audit_recorder):
        await make_user(db_session, user_id=9111, username="nobody")
        await make_role(db_session, role_id=9112, role_code="PLAIN")
        await link_user_role(db_session, user_id=9111, role_id=9112)

        actor = CurrentActor(user_id=9111, username="nobody")
        service = RoleService(db_session, audit=audit_recorder)
        with pytest.raises(PermissionDeniedError):
            await service.create(actor=actor, role_code="X", role_name="X")

        failures = audit_recorder.failures()
        assert len(failures) == 1
        assert str(failures[0].action) == str(AuditAction.ROLE_CREATE)

    async def test_unknown_actor_id_is_denied_fail_closed(self, db_session) -> None:
        """身份查不到（ID 伪造 / 已删除）时按无权限处理，不抛 404。

        授权层不应向外暴露"该用户是否存在"。
        """
        actor = CurrentActor(user_id=999_999, username="ghost")
        service = RoleService(db_session)
        with pytest.raises(PermissionDeniedError):
            await service.create(actor=actor, role_code="X", role_name="X")


# ===========================================================================
# 读取
# ===========================================================================
class TestRoleRead:
    async def test_get_returns_role(self, db_session) -> None:
        await make_role(db_session, role_id=9201, role_code="GETME")
        service = RoleService(db_session)
        role = await service.get(actor=ROOT, role_id=9201)
        assert role.role_code == "GETME"

    async def test_get_missing_returns_404(self, db_session) -> None:
        service = RoleService(db_session)
        with pytest.raises(NotFoundError, match="角色不存在"):
            await service.get(actor=ROOT, role_id=9202)

    async def test_get_excludes_soft_deleted(self, db_session) -> None:
        role = await make_role(db_session, role_id=9203, role_code="GONE")
        service = RoleService(db_session)
        await service.delete(actor=ROOT, role_id=role.id)
        with pytest.raises(NotFoundError):
            await service.get(actor=ROOT, role_id=9203)

    async def test_read_requires_authorization(self, db_session) -> None:
        """角色清单是敏感信息（暴露授权分层），读也必须受 ROLE_MANAGE 约束。"""
        await make_role(db_session, role_id=9204, role_code="SECRET")
        service = RoleService(db_session)
        with pytest.raises(PermissionDeniedError):
            await service.get(actor=ADMIN, role_id=9204)
        with pytest.raises(PermissionDeniedError):
            await service.list_roles(actor=ADMIN)

    async def test_list_pagination_and_keyword(self, db_session) -> None:
        for offset in range(5):
            await make_role(db_session, role_id=9300 + offset, role_code=f"L{offset}")
        service = RoleService(db_session)

        page = await service.list_roles(actor=ROOT, page_num=1, page_size=2)
        assert page.total == 5
        assert len(page.items) == 2
        assert page.page_num == 1

        filtered = await service.list_roles(actor=ROOT, keyword="L3")
        assert [role.role_code for role in filtered.items] == ["L3"]

    async def test_list_filters_by_status(self, db_session) -> None:
        await make_role(db_session, role_id=9401, role_code="ON", status=RoleStatus.ACTIVE)
        await make_role(db_session, role_id=9402, role_code="OFF", status=RoleStatus.DISABLED)
        service = RoleService(db_session)
        page = await service.list_roles(actor=ROOT, status=RoleStatus.DISABLED)
        assert [role.role_code for role in page.items] == ["OFF"]

    @pytest.mark.parametrize(("page_num", "page_size"), [(0, 20), (-1, 20), (1, 0), (1, 101)])
    async def test_invalid_pagination_returns_400(self, db_session, page_num, page_size) -> None:
        service = RoleService(db_session)
        with pytest.raises(BadRequestError):
            await service.list_roles(actor=ROOT, page_num=page_num, page_size=page_size)


# ===========================================================================
# 修改
# ===========================================================================
class TestRoleUpdate:
    async def test_update_name_and_description(self, db_session, audit_recorder) -> None:
        await make_role(db_session, role_id=9501, role_code="UPD")
        service = RoleService(db_session, audit=audit_recorder)
        role = await service.update(
            actor=ROOT, role_id=9501, role_name="新名", description="新描述"
        )
        assert role.role_name == "新名"
        event = audit_recorder.find(str(AuditAction.ROLE_UPDATE))
        assert event is not None
        assert event.before_data["role_name"] != event.after_data["role_name"]

    async def test_role_code_cannot_be_changed(self) -> None:
        """冻结契约：`update` 不接受 `role_code`。

        编码是角色的稳定标识（SUPER_ADMIN 判定、API 资源引用、审计检索都依赖它）。
        允许改码会引入"把 SUPER_ADMIN 改名为其它码 → 系统静默失去超管入口"
        这类跨模块后果，因此只能新建角色 + 迁移。
        """
        signature = inspect.signature(RoleService.update)
        assert "role_code" not in signature.parameters
        assert "data_scope" not in signature.parameters

    async def test_name_change_does_not_bump_version(self, db_session) -> None:
        """改名不改变任何人的权限集合 → 不递增版本。"""
        await make_role(db_session, role_id=9502, role_code="RENAME")
        before = await _version(db_session)
        service = RoleService(db_session)
        await service.update(actor=ROOT, role_id=9502, role_name="改名后")
        assert await _version(db_session) == before

    async def test_status_change_bumps_version(self, db_session) -> None:
        """禁用 / 启用直接改变该角色所有持有者的有效权限 → 必须递增版本。"""
        await make_role(db_session, role_id=9503, role_code="TOGGLE")
        before = await _version(db_session)
        service = RoleService(db_session)
        await service.update(actor=ROOT, role_id=9503, status=RoleStatus.DISABLED)
        assert await _version(db_session) == before + 1

    async def test_same_status_is_not_a_change(self, db_session) -> None:
        await make_role(db_session, role_id=9504, role_code="STABLE", status=RoleStatus.ACTIVE)
        before = await _version(db_session)
        service = RoleService(db_session)
        await service.update(actor=ROOT, role_id=9504, status=RoleStatus.ACTIVE)
        assert await _version(db_session) == before

    async def test_update_missing_role_returns_404(self, db_session) -> None:
        service = RoleService(db_session)
        with pytest.raises(NotFoundError):
            await service.update(actor=ROOT, role_id=9599, role_name="X")

    async def test_update_denied_is_audited(self, db_session, audit_recorder) -> None:
        await make_role(db_session, role_id=9505, role_code="PROTECTED")
        service = RoleService(db_session, audit=audit_recorder)
        with pytest.raises(PermissionDeniedError):
            await service.update(actor=ADMIN, role_id=9505, role_name="X")
        failures = audit_recorder.failures()
        assert len(failures) == 1
        assert str(failures[0].action) == str(AuditAction.ROLE_UPDATE)


# ===========================================================================
# 删除
# ===========================================================================
class TestRoleDelete:
    async def test_delete_refused_when_users_hold_role(self, db_session, audit_recorder) -> None:
        """静默清除 user_roles 会让用户"莫名失去角色"—— 属隐式权限变更，必须拒绝。"""
        await make_role(db_session, role_id=9601, role_code="HELD")
        await make_user(db_session, user_id=9602, username="holder")
        await link_user_role(db_session, user_id=9602, role_id=9601)

        service = RoleService(db_session, audit=audit_recorder)
        with pytest.raises(ConflictError, match="用户持有"):
            await service.delete(actor=ROOT, role_id=9601)
        failures = audit_recorder.failures()
        assert len(failures) == 1
        assert str(failures[0].action) == str(AuditAction.ROLE_DELETE)

    async def test_delete_refused_when_inheritance_references(
        self, db_session, audit_recorder
    ) -> None:
        """Spec 03 §4：删除父角色会让子角色静默失去权限 → 拒绝。"""
        await make_role(db_session, role_id=9611, role_code="PARENT")
        await make_role(db_session, role_id=9612, role_code="CHILD")
        await link_role_inheritance(db_session, parent_role_id=9611, child_role_id=9612)

        service = RoleService(db_session, audit=audit_recorder)
        with pytest.raises(ConflictError, match="角色继承"):
            await service.delete(actor=ROOT, role_id=9611)
        assert len(audit_recorder.failures()) == 1

    async def test_delete_refused_when_role_is_the_child_side(self, db_session) -> None:
        """子角色同样被引用 —— 拒绝对称生效，不能只看父侧。"""
        await make_role(db_session, role_id=9613, role_code="P2")
        await make_role(db_session, role_id=9614, role_code="C2")
        await link_role_inheritance(db_session, parent_role_id=9613, child_role_id=9614)
        service = RoleService(db_session)
        with pytest.raises(ConflictError, match="角色继承"):
            await service.delete(actor=ROOT, role_id=9614)

    async def test_delete_clears_own_grants_and_custom_scope(self, db_session) -> None:
        """自己的从属数据（授权 / CUSTOM 行）→ 清理，否则会留下无主"僵尸授权"。"""
        await make_role(db_session, role_id=9621, role_code="CLEANUP", data_scope=DataScope.CUSTOM)
        await make_department(db_session, department_id=1, department_code="HQ")
        page = await make_permission_resource(
            db_session,
            resource_id=9622,
            resource_type=PermissionResourceType.PAGE,
            resource_code="p",
            route_path="/p",
            component_path="p",
        )
        field = await make_permission_resource(
            db_session,
            resource_id=9623,
            resource_type=PermissionResourceType.FIELD,
            resource_code="p.phone",
            field_key="phone",
            owner_resource_id=page.id,
        )
        await link_role_permission(db_session, role_id=9621, resource_id=page.id)
        await link_role_field_permission(
            db_session, role_id=9621, field_id=field.id, access_level=FieldAccessLevel.VISIBLE
        )
        await link_role_custom_scope(db_session, role_id=9621, department_id=1)
        await db_session.flush()

        service = RoleService(db_session)
        deleted = await service.delete(actor=ROOT, role_id=9621)

        assert deleted.deleted_at is not None
        assert deleted.status is RoleStatus.DISABLED

        from app.models import RoleFieldPermission, RolePermission

        grants = (
            (
                await db_session.execute(
                    select(RolePermission.resource_id).where(RolePermission.role_id == 9621)
                )
            )
            .scalars()
            .all()
        )
        assert grants == []
        field_grants = (
            (
                await db_session.execute(
                    select(RoleFieldPermission.field_id).where(RoleFieldPermission.role_id == 9621)
                )
            )
            .scalars()
            .all()
        )
        assert field_grants == []
        custom = (
            (
                await db_session.execute(
                    select(RoleCustomScopeDepartment.department_id).where(
                        RoleCustomScopeDepartment.role_id == 9621
                    )
                )
            )
            .scalars()
            .all()
        )
        assert custom == []

    async def test_delete_records_cleared_ids_in_audit(self, db_session, audit_recorder) -> None:
        """清理内容必须进审计：否则"删角色顺手删了什么权限"无从追溯。"""
        await make_role(db_session, role_id=9631, role_code="AUDITED")
        page = await make_permission_resource(
            db_session,
            resource_id=9632,
            resource_type=PermissionResourceType.PAGE,
            resource_code="p2",
            route_path="/p2",
            component_path="p2",
        )
        await link_role_permission(db_session, role_id=9631, resource_id=page.id)

        service = RoleService(db_session, audit=audit_recorder)
        await service.delete(actor=ROOT, role_id=9631)
        event = audit_recorder.find(str(AuditAction.ROLE_DELETE))
        assert event is not None
        assert event.after_data["cleared_resource_ids"] == [9632]

    async def test_delete_bumps_version(self, db_session) -> None:
        await make_role(db_session, role_id=9641, role_code="BUMP")
        before = await _version(db_session)
        service = RoleService(db_session)
        await service.delete(actor=ROOT, role_id=9641)
        assert await _version(db_session) == before + 1

    async def test_delete_missing_returns_404(self, db_session) -> None:
        service = RoleService(db_session)
        with pytest.raises(NotFoundError):
            await service.delete(actor=ROOT, role_id=9699)

    async def test_delete_is_soft_only(self, db_session) -> None:
        """绝不物理删除（AGENTS.md §7 / Spec 00 §6）。"""
        await make_role(db_session, role_id=9651, role_code="SOFTONLY")
        service = RoleService(db_session)
        await service.delete(actor=ROOT, role_id=9651)
        row = (await db_session.execute(select(Role.status).where(Role.id == 9651))).scalar_one()
        assert row is RoleStatus.DISABLED

    async def test_delete_denied_is_audited(self, db_session, audit_recorder) -> None:
        await make_role(db_session, role_id=9661, role_code="GUARDED")
        service = RoleService(db_session, audit=audit_recorder)
        with pytest.raises(PermissionDeniedError):
            await service.delete(actor=ADMIN, role_id=9661)
        failures = audit_recorder.failures()
        assert len(failures) == 1
        assert str(failures[0].action) == str(AuditAction.ROLE_DELETE)
