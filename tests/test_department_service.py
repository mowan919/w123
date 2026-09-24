"""部门服务测试（integration）。

对应 Verification `001-organization-user.md`：
    - Department tree 可正确建立
    - Department 支持逻辑删除
    - Department Admin 数据范围为当前部门 + 所有子部门
    - 多部门层级查询无越权

并覆盖 Spec `10 §10`（范围必须在 SQL 生效）与 `10 §3`（不得改参数绕行）。
"""

from __future__ import annotations

import pytest

from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.scope import DataScope
from app.models.enums import DepartmentStatus
from app.repositories.department import DepartmentRepository
from app.services.data_scope import DataScopeResolver
from app.services.department import DepartmentService
from tests.conftest import RecordingAuditRecorder
from tests.factories import make_department, make_user

pytestmark = pytest.mark.integration


async def _seed_tree(session) -> None:
    """构造测试树。

    1 总部
    ├── 2 研发中心
    │   ├── 3 前端组
    │   └── 4 后端组
    └── 5 市场部
    6 独立子公司（根）
    """
    await make_department(session, department_id=1, department_code="HQ", department_name="总部")
    await make_department(
        session, department_id=2, department_code="RD", parent_id=1, department_name="研发中心"
    )
    await make_department(
        session, department_id=3, department_code="RD-FE", parent_id=2, department_name="前端组"
    )
    await make_department(
        session, department_id=4, department_code="RD-BE", parent_id=2, department_name="后端组"
    )
    await make_department(
        session, department_id=5, department_code="MKT", parent_id=1, department_name="市场部"
    )
    await make_department(
        session, department_id=6, department_code="SUB", department_name="独立子公司"
    )


def _dept_admin(
    department_id: int, *, scope: DataScope = DataScope.DEPARTMENT_CHILDREN
) -> CurrentActor:
    return CurrentActor(
        user_id=7001,
        username="dept-admin",
        role_codes=frozenset({"DEPARTMENT_ADMIN"}),
        data_scope=scope,
        department_id=department_id,
    )


# ---------------------------------------------------------------------------
# 数据范围解析
# ---------------------------------------------------------------------------
class TestDataScopeResolution:
    async def test_department_children_includes_self_and_descendants(self, db_session) -> None:
        await _seed_tree(db_session)
        resolver = DataScopeResolver(DepartmentRepository(db_session))
        scope = await resolver.resolve(_dept_admin(2))
        assert scope.department_ids == frozenset({2, 3, 4})
        assert scope.is_unrestricted_departments is False

    async def test_department_scope_is_own_department_only(self, db_session) -> None:
        await _seed_tree(db_session)
        resolver = DataScopeResolver(DepartmentRepository(db_session))
        scope = await resolver.resolve(_dept_admin(2, scope=DataScope.DEPARTMENT))
        assert scope.department_ids == frozenset({2})

    async def test_super_admin_is_global(self, db_session) -> None:
        resolver = DataScopeResolver(DepartmentRepository(db_session))
        scope = await resolver.resolve(CurrentActor.super_admin(user_id=1, username="root"))
        assert scope.is_unrestricted_departments is True

    async def test_actor_without_department_gets_empty_scope(self, db_session) -> None:
        """fail-closed：未分配部门 → 空集合，绝不退化为全局。"""
        resolver = DataScopeResolver(DepartmentRepository(db_session))
        actor = CurrentActor(
            user_id=9, username="no-dept", data_scope=DataScope.DEPARTMENT_CHILDREN
        )
        scope = await resolver.resolve(actor)
        assert scope.department_ids == frozenset()
        assert scope.denies_all_departments is True

    async def test_self_scope_is_actor_only_and_denies_departments(self, db_session) -> None:
        resolver = DataScopeResolver(DepartmentRepository(db_session))
        scope = await resolver.resolve(
            CurrentActor(user_id=9, username="u", data_scope=DataScope.SELF, department_id=2)
        )
        assert scope.restrict_to_actor is True
        assert scope.department_ids == frozenset()

    async def test_custom_scope_uses_provided_ids(self, db_session) -> None:
        resolver = DataScopeResolver(DepartmentRepository(db_session))
        actor = CurrentActor(
            user_id=9,
            username="u",
            data_scope=DataScope.CUSTOM,
            custom_department_ids=frozenset({3, 5}),
        )
        scope = await resolver.resolve(actor)
        assert scope.department_ids == frozenset({3, 5})

    async def test_custom_scope_without_configuration_is_empty(self, db_session) -> None:
        """DD-07 未冻结 → 未配置时按拒绝处理。"""
        resolver = DataScopeResolver(DepartmentRepository(db_session))
        actor = CurrentActor(user_id=9, username="u", data_scope=DataScope.CUSTOM)
        scope = await resolver.resolve(actor)
        assert scope.department_ids == frozenset()


# ---------------------------------------------------------------------------
# 部门树
# ---------------------------------------------------------------------------
class TestDepartmentTree:
    async def test_super_admin_sees_full_tree(self, db_session) -> None:
        await _seed_tree(db_session)
        service = DepartmentService(db_session)
        roots = await service.list_tree(actor=CurrentActor.super_admin(user_id=1, username="root"))
        assert [node.id for node in roots] == [1, 6]
        hq = roots[0]
        assert sorted(child.id for child in hq.children) == [2, 5]
        rd = next(child for child in hq.children if child.id == 2)
        assert sorted(grandchild.id for grandchild in rd.children) == [3, 4]

    async def test_department_admin_sees_only_own_subtree(self, db_session) -> None:
        await _seed_tree(db_session)
        service = DepartmentService(db_session)
        roots = await service.list_tree(actor=_dept_admin(2))
        # 2 的父部门 1 在范围外 → 2 作为根呈现，且不含 1、5、6
        assert [node.id for node in roots] == [2]
        assert sorted(child.id for child in roots[0].children) == [3, 4]

    async def test_get_out_of_scope_department_is_denied(self, db_session) -> None:
        await _seed_tree(db_session)
        service = DepartmentService(db_session)
        with pytest.raises(PermissionDeniedError):
            await service.get(actor=_dept_admin(2), department_id=5)

    async def test_get_missing_department_raises_not_found(self, db_session) -> None:
        await _seed_tree(db_session)
        service = DepartmentService(db_session)
        with pytest.raises(NotFoundError):
            await service.get(
                actor=CurrentActor.super_admin(user_id=1, username="root"), department_id=999999
            )


# ---------------------------------------------------------------------------
# 创建
# ---------------------------------------------------------------------------
class TestDepartmentCreate:
    async def test_department_admin_creates_child_in_scope(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        created = await service.create(
            actor=_dept_admin(2),
            department_code="RD-OPS",
            department_name="运维组",
            parent_id=2,
        )
        assert created.parent_id == 2
        assert created.status is DepartmentStatus.ACTIVE
        assert created.id > 0
        assert recorder.actions() == ["DEPARTMENT_CREATE"]
        assert recorder.results() == ["SUCCESS"]

    async def test_department_admin_cannot_create_under_out_of_scope_parent(
        self, db_session
    ) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.create(
                actor=_dept_admin(2), department_code="X1", department_name="越权", parent_id=5
            )

        # 越权尝试必须留痕
        assert recorder.results() == ["FAILURE"]
        assert recorder.find("DEPARTMENT_CREATE") is not None

    async def test_department_admin_cannot_create_root_department(self, db_session) -> None:
        await _seed_tree(db_session)
        service = DepartmentService(db_session)
        with pytest.raises(PermissionDeniedError):
            await service.create(
                actor=_dept_admin(2), department_code="X2", department_name="根越权", parent_id=None
            )

    async def test_code_can_be_reused_after_soft_delete(self, db_session) -> None:
        """软删除感知唯一：删除后可复用同一 department_code。"""
        await _seed_tree(db_session)
        root_actor = CurrentActor.super_admin(user_id=1, username="root")
        service = DepartmentService(db_session)

        await service.delete(actor=root_actor, department_id=5)
        reused = await service.create(
            actor=root_actor,
            department_code="MKT",
            department_name="市场部(重建)",
        )
        assert reused.id != 5
        assert reused.department_code == "MKT"

    async def test_duplicate_active_code_is_conflict(self, db_session) -> None:
        await _seed_tree(db_session)
        service = DepartmentService(db_session)
        with pytest.raises(ConflictError):
            await service.create(
                actor=CurrentActor.super_admin(user_id=1, username="root"),
                department_code="HQ",
                department_name="重复编码",
            )


# ---------------------------------------------------------------------------
# 修改 / 禁用
# ---------------------------------------------------------------------------
class TestDepartmentUpdateAndDisable:
    async def test_rename_and_move_within_scope(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        updated = await service.update(
            actor=CurrentActor.super_admin(user_id=1, username="root"),
            department_id=3,
            department_name="前端组(改名)",
            parent_id=1,
        )
        assert updated.department_name == "前端组(改名)"
        assert updated.parent_id == 1
        event = recorder.find("DEPARTMENT_UPDATE")
        assert event is not None
        assert event.before_data["parent_id"] == 2
        assert event.after_data["parent_id"] == 1

    async def test_cannot_move_department_under_own_descendant(self, db_session) -> None:
        await _seed_tree(db_session)
        service = DepartmentService(db_session)
        with pytest.raises(ConflictError, match="循环"):
            await service.update(
                actor=CurrentActor.super_admin(user_id=1, username="root"),
                department_id=2,
                parent_id=3,
            )

    async def test_cannot_set_parent_to_self(self, db_session) -> None:
        await _seed_tree(db_session)
        service = DepartmentService(db_session)
        with pytest.raises(BadRequestError, match="自身"):
            await service.update(
                actor=CurrentActor.super_admin(user_id=1, username="root"),
                department_id=2,
                parent_id=2,
            )

    async def test_department_admin_cannot_update_out_of_scope(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError):
            await service.update(actor=_dept_admin(2), department_id=5, department_name="越权改名")
        assert recorder.results() == ["FAILURE"]

    async def test_department_admin_cannot_move_into_out_of_scope_parent(self, db_session) -> None:
        await _seed_tree(db_session)
        service = DepartmentService(db_session)
        with pytest.raises(PermissionDeniedError):
            await service.update(actor=_dept_admin(2), department_id=3, parent_id=5)

    async def test_disable_department(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        disabled = await service.disable(actor=_dept_admin(2), department_id=3)
        assert disabled.status is DepartmentStatus.DISABLED
        assert recorder.actions() == ["DEPARTMENT_DISABLE"]


# ---------------------------------------------------------------------------
# 逻辑删除
# ---------------------------------------------------------------------------
class TestDepartmentLogicalDelete:
    async def test_delete_refused_when_children_exist(self, db_session) -> None:
        await _seed_tree(db_session)
        service = DepartmentService(db_session)
        with pytest.raises(ConflictError, match="子部门"):
            await service.delete(
                actor=CurrentActor.super_admin(user_id=1, username="root"), department_id=2
            )

    async def test_delete_refused_when_users_exist_in_subtree(self, db_session) -> None:
        await _seed_tree(db_session)
        await make_user(db_session, user_id=8001, username="deep-user", department_id=3)
        service = DepartmentService(db_session)
        # 3 无子部门，但自身有用户
        with pytest.raises(ConflictError, match="在册用户"):
            await service.delete(
                actor=CurrentActor.super_admin(user_id=1, username="root"), department_id=3
            )

    async def test_delete_succeeds_for_empty_leaf(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        deleted = await service.delete(
            actor=CurrentActor.super_admin(user_id=1, username="root"),
            department_id=3,
        )
        assert deleted.deleted_at is not None
        assert recorder.actions() == ["DEPARTMENT_DELETE"]

        # 删除后普通查询不再返回（Spec 02 §5）
        with pytest.raises(NotFoundError):
            await service.get(
                actor=CurrentActor.super_admin(user_id=1, username="root"),
                department_id=3,
            )

    async def test_deleted_department_disappears_from_tree(self, db_session) -> None:
        await _seed_tree(db_session)
        service = DepartmentService(db_session)
        actor = CurrentActor.super_admin(user_id=1, username="root")
        await service.delete(actor=actor, department_id=5)
        roots = await service.list_tree(actor=actor)
        assert [node.id for node in roots] == [1, 6]
        assert sorted(child.id for child in roots[0].children) == [2]

    async def test_department_admin_cannot_delete_out_of_scope(self, db_session) -> None:
        await _seed_tree(db_session)
        service = DepartmentService(db_session)
        with pytest.raises(PermissionDeniedError):
            await service.delete(actor=_dept_admin(2), department_id=6)
