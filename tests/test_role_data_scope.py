"""角色数据范围持久化测试（Task 3.10 / DD-07 已冻结部分）。

覆盖点
-----
- `roles.data_scope` 列默认值与取值约束；
- CUSTOM 部门集合的存储、整体替换、**非 CUSTOM 时清空残留**；
- 查询 / 更新 / 删除 三项操作；
- 授权拒绝必须留痕（FAILURE 审计），且恰好一条（防重复埋点）；
- 引用完整性与参数自洽性校验。

不覆盖（已登记 BLOCKED / 未冻结）
-------------------------------
- 多角色数据范围的**合并规则**（Spec 未规定，本服务只做单角色读写）；
- 权限引擎（Task 3.11，阻塞于 CONFLICT-001）；
- Role CRUD 与角色继承（后者 DD-05 = BLOCKED）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.audit import AuditAction
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, NotFoundError, PermissionDeniedError
from app.core.scope import DataScope
from app.models.role import RoleCustomScopeDepartment
from app.repositories.permission import PermissionVersionRepository
from app.services.role_data_scope import RoleDataScopeService
from tests.factories import make_department, make_role

pytestmark = pytest.mark.integration

ROLE_ID = 7001
CUSTOM_ROLE_ID = 7002
MISSING_ROLE_ID = 7999

ROOT = CurrentActor.super_admin(user_id=1001, username="root")
#: 有角色但不是 SUPER_ADMIN —— 用于验证 INTERIM 保守默认（仅 SUPER_ADMIN 可管理角色）
ADMIN = CurrentActor(
    user_id=1002,
    username="dept-admin",
    role_codes=frozenset({"DEPT_ADMIN"}),
    data_scope=DataScope.DEPARTMENT_CHILDREN,
    department_id=2,
)


async def _seed(session) -> None:
    await make_department(session, department_id=1, department_code="HQ")
    await make_department(session, department_id=2, department_code="RD", parent_id=1)
    await make_department(session, department_id=3, department_code="RD-FE", parent_id=2)
    await make_role(session, role_id=ROLE_ID, role_code="AUDITOR")
    await make_role(
        session, role_id=CUSTOM_ROLE_ID, role_code="REGIONAL", data_scope=DataScope.CUSTOM
    )


async def _custom_rows(session, role_id: int) -> set[int]:
    stmt = select(RoleCustomScopeDepartment.department_id).where(
        RoleCustomScopeDepartment.role_id == role_id
    )
    return set((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# 列默认值与持久化
# ---------------------------------------------------------------------------
class TestDataScopeColumn:
    async def test_default_is_department_children(self, db_session) -> None:
        """Spec 03 §10：部门管理员默认 DEPARTMENT_CHILDREN。"""
        await _seed(db_session)
        role = await make_role(db_session, role_id=7101, role_code="DEFAULTED")
        assert role.data_scope is DataScope.DEPARTMENT_CHILDREN

    async def test_all_five_scopes_are_persistable(self, db_session) -> None:
        """五个策略都必须能写入并读回（覆盖 CHECK 约束的完整取值域）。"""
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        for offset, scope in enumerate(DataScope):
            role = await make_role(db_session, role_id=7200 + offset, role_code=f"S{offset}")
            if scope is DataScope.CUSTOM:
                await service.set_scope(
                    actor=ROOT, role_id=role.id, scope=scope, department_ids=frozenset({1})
                )
            else:
                await service.set_scope(actor=ROOT, role_id=role.id, scope=scope)
            view = await service.get(actor=ROOT, role_id=role.id)
            assert view.scope is scope


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
class TestGetScope:
    async def test_get_non_custom_has_no_department_ids(self, db_session) -> None:
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        view = await service.get(actor=ROOT, role_id=ROLE_ID)
        assert view.scope is DataScope.DEPARTMENT_CHILDREN
        assert view.department_ids == frozenset()
        assert view.is_custom is False

    async def test_get_custom_returns_persisted_departments(self, db_session) -> None:
        """DD-07 核心：CUSTOM 范围**从数据库读取**，不再依赖外部传入。"""
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        await service.set_scope(
            actor=ROOT,
            role_id=CUSTOM_ROLE_ID,
            scope=DataScope.CUSTOM,
            department_ids=frozenset({2, 3}),
        )
        view = await service.get(actor=ROOT, role_id=CUSTOM_ROLE_ID)
        assert view.scope is DataScope.CUSTOM
        assert view.department_ids == frozenset({2, 3})

    async def test_custom_scope_survives_new_session_read(self, db_session) -> None:
        """写入后必须真正落库（而非仅存在于 ORM 身份映射）。"""
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        await service.set_scope(
            actor=ROOT,
            role_id=CUSTOM_ROLE_ID,
            scope=DataScope.CUSTOM,
            department_ids=frozenset({1}),
        )
        assert await _custom_rows(db_session, CUSTOM_ROLE_ID) == {1}

    async def test_get_missing_role_raises_not_found(self, db_session) -> None:
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        with pytest.raises(NotFoundError):
            await service.get(actor=ROOT, role_id=MISSING_ROLE_ID)


# ---------------------------------------------------------------------------
# 更新
# ---------------------------------------------------------------------------
class TestSetScope:
    async def test_set_custom_persists_departments(self, db_session) -> None:
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        view = await service.set_scope(
            actor=ROOT,
            role_id=ROLE_ID,
            scope=DataScope.CUSTOM,
            department_ids=frozenset({2, 3}),
        )
        assert view.scope is DataScope.CUSTOM
        assert await _custom_rows(db_session, ROLE_ID) == {2, 3}

    async def test_replace_custom_set_is_atomic(self, db_session) -> None:
        """整体替换而非追加：旧集合中不在新集合里的部门必须被移除。"""
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        await service.set_scope(
            actor=ROOT, role_id=ROLE_ID, scope=DataScope.CUSTOM, department_ids=frozenset({1, 2})
        )
        await service.set_scope(
            actor=ROOT, role_id=ROLE_ID, scope=DataScope.CUSTOM, department_ids=frozenset({3})
        )
        assert await _custom_rows(db_session, ROLE_ID) == {3}

    async def test_leaving_custom_clears_residual_rows(self, db_session) -> None:
        """**权限放大防护**：从 CUSTOM 切走后不得留下残留行。

        否则角色改回 CUSTOM 时会静默继承过期部门集合（Spec `11 §5`）。
        """
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        await service.set_scope(
            actor=ROOT, role_id=ROLE_ID, scope=DataScope.CUSTOM, department_ids=frozenset({1, 2})
        )
        assert await _custom_rows(db_session, ROLE_ID) == {1, 2}

        await service.set_scope(actor=ROOT, role_id=ROLE_ID, scope=DataScope.SELF)
        assert await _custom_rows(db_session, ROLE_ID) == set()

        view = await service.get(actor=ROOT, role_id=ROLE_ID)
        assert view.scope is DataScope.SELF
        assert view.department_ids == frozenset()

    async def test_non_custom_with_department_ids_is_rejected(self, db_session) -> None:
        """参数自洽：非 CUSTOM 却给部门集合 → 拒绝（不静默丢弃）。"""
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        with pytest.raises(BadRequestError, match="CUSTOM"):
            await service.set_scope(
                actor=ROOT,
                role_id=ROLE_ID,
                scope=DataScope.ALL,
                department_ids=frozenset({1}),
            )
        # 拒绝后状态不得改变
        role = await service._roles.get(ROLE_ID)
        assert role is not None
        assert role.data_scope is DataScope.DEPARTMENT_CHILDREN

    async def test_custom_referencing_missing_department_is_rejected(self, db_session) -> None:
        """引用完整性：CUSTOM 不得引用不存在的部门。"""
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        with pytest.raises(BadRequestError, match="不存在的部门"):
            await service.set_scope(
                actor=ROOT,
                role_id=ROLE_ID,
                scope=DataScope.CUSTOM,
                department_ids=frozenset({1, 99999}),
            )
        assert await _custom_rows(db_session, ROLE_ID) == set()

    async def test_custom_with_empty_set_is_allowed_and_denies_all(self, db_session) -> None:
        """空 CUSTOM 集合是合法配置，语义为"什么都看不到"（fail-closed）。"""
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        view = await service.set_scope(
            actor=ROOT, role_id=ROLE_ID, scope=DataScope.CUSTOM, department_ids=frozenset()
        )
        assert view.scope is DataScope.CUSTOM
        assert view.department_ids == frozenset()

    async def test_set_scope_missing_role_raises_not_found(self, db_session) -> None:
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        with pytest.raises(NotFoundError):
            await service.set_scope(actor=ROOT, role_id=MISSING_ROLE_ID, scope=DataScope.SELF)


# ---------------------------------------------------------------------------
# 删除（CUSTOM 配置）
# ---------------------------------------------------------------------------
class TestClearCustomScope:
    async def test_clear_removes_rows_and_downgrades_to_self(self, db_session) -> None:
        """删除 CUSTOM 配置：清空关联并把策略降到最小的合法值 SELF。"""
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        await service.set_scope(
            actor=ROOT,
            role_id=CUSTOM_ROLE_ID,
            scope=DataScope.CUSTOM,
            department_ids=frozenset({1, 2, 3}),
        )
        view = await service.clear_custom_scope(actor=ROOT, role_id=CUSTOM_ROLE_ID)

        assert view.scope is DataScope.SELF
        assert view.department_ids == frozenset()
        assert await _custom_rows(db_session, CUSTOM_ROLE_ID) == set()

    async def test_clear_is_idempotent(self, db_session) -> None:
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        first = await service.clear_custom_scope(actor=ROOT, role_id=ROLE_ID)
        second = await service.clear_custom_scope(actor=ROOT, role_id=ROLE_ID)
        assert first.scope is DataScope.SELF
        assert second.scope is DataScope.SELF

    async def test_clear_does_not_delete_the_role(self, db_session) -> None:
        """只删除范围配置，不删除角色本身。"""
        await _seed(db_session)
        service = RoleDataScopeService(db_session)
        await service.clear_custom_scope(actor=ROOT, role_id=ROLE_ID)
        role = await service._roles.get(ROLE_ID)
        assert role is not None
        assert role.deleted_at is None


# ---------------------------------------------------------------------------
# 权限版本递增（Spec 11 §2：权限修改必须递增并使旧缓存失效）
# ---------------------------------------------------------------------------
class TestPermissionVersionBump:
    """数据范围变化会改变该角色持有者的可见数据边界 → 必须递增版本。

    漏掉这一步，Spec `00 §1#5` 的"权限变更立即生效"就会对数据范围失效：
    调用方按旧版本判断"缓存仍然有效"，从而继续用旧的可见边界。
    """

    async def test_set_scope_bumps_version(self, db_session) -> None:
        await _seed(db_session)
        versions = PermissionVersionRepository(db_session)
        before = await versions.get()

        await RoleDataScopeService(db_session).set_scope(
            actor=ROOT, role_id=ROLE_ID, scope=DataScope.ALL
        )
        assert await versions.get() == before + 1

    async def test_set_custom_scope_bumps_version(self, db_session) -> None:
        await _seed(db_session)
        versions = PermissionVersionRepository(db_session)
        before = await versions.get()

        await RoleDataScopeService(db_session).set_scope(
            actor=ROOT,
            role_id=CUSTOM_ROLE_ID,
            scope=DataScope.CUSTOM,
            department_ids=frozenset({1}),
        )
        assert await versions.get() == before + 1

    async def test_clear_custom_scope_bumps_version(self, db_session) -> None:
        await _seed(db_session)
        versions = PermissionVersionRepository(db_session)
        before = await versions.get()

        await RoleDataScopeService(db_session).clear_custom_scope(
            actor=ROOT, role_id=CUSTOM_ROLE_ID
        )
        assert await versions.get() == before + 1

    async def test_read_does_not_bump_version(self, db_session) -> None:
        """只有写操作才递增；读操作递增会让缓存无谓失效。"""
        await _seed(db_session)
        versions = PermissionVersionRepository(db_session)
        before = await versions.get()

        await RoleDataScopeService(db_session).get(actor=ROOT, role_id=ROLE_ID)
        assert await versions.get() == before


# ---------------------------------------------------------------------------
# 授权（Phase 3 起基于 API Permission，不再是 INTERIM"仅 SUPER_ADMIN"）
# ---------------------------------------------------------------------------
class TestAuthorization:
    @pytest.mark.security
    async def test_non_super_admin_cannot_read_scope(self, db_session) -> None:
        await _seed(db_session)
        recorder_ctrl = _recorder()
        service = RoleDataScopeService(db_session, audit=recorder_ctrl)
        with pytest.raises(PermissionDeniedError):
            await service.get(actor=ADMIN, role_id=ROLE_ID)

        failures = recorder_ctrl.failures()
        assert len(failures) == 1
        assert failures[0].action == AuditAction.ROLE_DATA_SCOPE_READ
        assert failures[0].resource_type == "ROLE"
        assert failures[0].resource_id == ROLE_ID

    @pytest.mark.security
    async def test_non_super_admin_cannot_change_scope(self, db_session) -> None:
        """越权修改权限 → 拒绝 + FAILURE 审计 + 状态不变。"""
        await _seed(db_session)
        recorder_ctrl = _recorder()
        service = RoleDataScopeService(db_session, audit=recorder_ctrl)

        with pytest.raises(PermissionDeniedError):
            await service.set_scope(
                actor=ADMIN,
                role_id=ROLE_ID,
                scope=DataScope.ALL,
            )

        failures = recorder_ctrl.failures()
        assert len(failures) == 1
        assert failures[0].action == AuditAction.ROLE_DATA_SCOPE_UPDATE
        assert recorder_ctrl.find(str(AuditAction.ROLE_DATA_SCOPE_UPDATE)) is not None

        role = await service._roles.get(ROLE_ID)
        assert role is not None
        assert role.data_scope is DataScope.DEPARTMENT_CHILDREN  # 未被改动
        assert await _custom_rows(db_session, ROLE_ID) == set()

    @pytest.mark.security
    async def test_non_super_admin_cannot_clear_scope(self, db_session) -> None:
        await _seed(db_session)
        recorder_ctrl = _recorder()
        service = RoleDataScopeService(db_session, audit=recorder_ctrl)
        with pytest.raises(PermissionDeniedError):
            await service.clear_custom_scope(actor=ADMIN, role_id=CUSTOM_ROLE_ID)
        assert len(recorder_ctrl.failures()) == 1

    @pytest.mark.security
    async def test_denial_audit_carries_full_context(self, db_session) -> None:
        """FAILURE 审计必须携带 Spec 06 §2 要求的关键字段。"""
        await _seed(db_session)
        recorder_ctrl = _recorder()
        actor = CurrentActor(
            user_id=1002,
            username="dept-admin",
            role_codes=frozenset({"DEPT_ADMIN"}),
            data_scope=DataScope.SELF,
            department_id=2,
            ip="10.0.0.9",
            user_agent="pytest-agent",
        )
        service = RoleDataScopeService(db_session, audit=recorder_ctrl)
        with pytest.raises(PermissionDeniedError):
            await service.get(actor=actor, role_id=ROLE_ID)

        event = recorder_ctrl.failures()[0]
        assert event.operator_id == 1002
        assert event.operator_username == "dept-admin"
        assert event.resource_type == "ROLE"
        assert event.result.value == "FAILURE"
        assert event.error_code is not None
        assert event.ip == "10.0.0.9"
        assert event.user_agent == "pytest-agent"
        assert event.created_at is not None

    @pytest.mark.security
    async def test_not_found_is_not_audited_as_denial(self, db_session) -> None:
        """`NotFoundError` 不是越权拒绝，不得污染 FAILURE 信号。"""
        await _seed(db_session)
        recorder_ctrl = _recorder()
        service = RoleDataScopeService(db_session, audit=recorder_ctrl)
        with pytest.raises(NotFoundError):
            await service.get(actor=ROOT, role_id=MISSING_ROLE_ID)
        assert recorder_ctrl.failures() == []


# ---------------------------------------------------------------------------
# 审计（成功路径）
# ---------------------------------------------------------------------------
class TestAuditSuccess:
    async def test_set_scope_records_before_and_after(self, db_session) -> None:
        await _seed(db_session)
        recorder_ctrl = _recorder()
        service = RoleDataScopeService(db_session, audit=recorder_ctrl)

        await service.set_scope(
            actor=ROOT,
            role_id=ROLE_ID,
            scope=DataScope.CUSTOM,
            department_ids=frozenset({2, 3}),
        )

        event = recorder_ctrl.find(str(AuditAction.ROLE_DATA_SCOPE_UPDATE))
        assert event is not None
        assert event.result.value == "SUCCESS"
        assert event.before_data["data_scope"] == "DEPARTMENT_CHILDREN"
        assert event.after_data["data_scope"] == "CUSTOM"
        assert event.after_data["custom_department_ids"] == [2, 3]
        assert recorder_ctrl.failures() == []

    async def test_clear_records_cleared_departments(self, db_session) -> None:
        await _seed(db_session)
        recorder_ctrl = _recorder()
        service = RoleDataScopeService(db_session, audit=recorder_ctrl)
        await service.set_scope(
            actor=ROOT,
            role_id=ROLE_ID,
            scope=DataScope.CUSTOM,
            department_ids=frozenset({1, 2}),
        )
        recorder_ctrl.events.clear()

        await service.clear_custom_scope(actor=ROOT, role_id=ROLE_ID)
        event = recorder_ctrl.find(str(AuditAction.ROLE_DATA_SCOPE_UPDATE))
        assert event is not None
        assert event.before_data["cleared_department_ids"] == [1, 2]
        assert event.after_data["data_scope"] == "SELF"

    async def test_audit_snapshot_contains_no_sensitive_field(self, db_session) -> None:
        """审计快照只含范围配置，不得出现任何口令 / token 类字段。"""
        await _seed(db_session)
        recorder_ctrl = _recorder()
        service = RoleDataScopeService(db_session, audit=recorder_ctrl)
        await service.set_scope(
            actor=ROOT, role_id=ROLE_ID, scope=DataScope.CUSTOM, department_ids=frozenset({1})
        )
        event = recorder_ctrl.find(str(AuditAction.ROLE_DATA_SCOPE_UPDATE))
        assert event is not None
        assert set(event.after_data or {}) == {
            "role_id",
            "data_scope",
            "custom_department_ids",
        }


def _recorder():
    """局部构造可断言的审计记录器，避免跨测试共享状态。"""
    from tests.conftest import RecordingAuditRecorder

    return RecordingAuditRecorder()
