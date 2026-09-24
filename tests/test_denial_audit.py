"""FIX-002 / RISK-002：**拒绝路径必须全量留痕**（security）。

为什么单独一个文件
-----------------
FIX-002 的核心不是"某个操作能留痕"，而是"**不存在留不下痕的拒绝路径**"。
这属于**穷尽性**断言，需要逐条覆盖每个拒绝分支，
因此与 `test_audit_integration.py`（验证"正常操作会留痕"）分开放，
避免把穷尽性用例淹没在正向用例里。

覆盖的拒绝面
-----------
用户侧（`UserService`）：
    读越权 / 改越权 / 篡改 department_id / 移出部门 / 跨范围禁用 /
    跨范围启用 / 跨范围删除 / 跨范围重置口令 / 跨范围改角色 /
    授予特权角色 / 创建时授予特权角色 / 操作 SUPER_ADMIN。
部门侧（`DepartmentService`）：
    读越权 / 创建根越权 / 创建子越权 / 禁用越权 / 删除越权 /
    **移到根层级越权**（原实现遗漏留痕的分支）。

RISK-002（安全不变量）：
    禁用 / 逻辑删除系统中的**最后一个** SUPER_ADMIN 必须被拒绝且留 FAILURE。

Spec 依据：`06 §2`（15 字段）、`06 §3`（Trace 贯穿）、
`10 §3`（服务端二次校验）、`10 §8`（关键安全操作必须可审计）。
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime

import pytest

from app.audit import AuditAction, AuditEvent, AuditResult
from app.auth.actor import SUPER_ADMIN_ROLE_CODE, CurrentActor
from app.core.context import trace_context
from app.core.errors import ConflictError, PermissionDeniedError
from app.core.scope import DataScope
from app.db.base import utc_now
from app.models.enums import UserStatus
from app.repositories.user import UserRepository
from app.services.department import DepartmentService
from app.services.user import UserService
from tests.conftest import RecordingAuditRecorder
from tests.factories import link_user_role, make_department, make_role, make_user

pytestmark = pytest.mark.security

SUPER_ROLE_ID = 9001
DEPT_ADMIN_ROLE_ID = 9002
AUDITOR_ROLE_ID = 9003

PW_A = "Alpha-Passw0rd!01"

PERMISSION_DENIED = 403001
CONFLICT = 409001

#: FIX-002 明确要求拒绝审计至少携带的字段。
REQUIRED_DENIAL_FIELDS = {
    "operator_id",
    "operator_username",
    "action",
    "resource_type",
    "resource_id",
    "result",
    "error_code",
    "trace_id",
    "request_id",
    "ip",
    "user_agent",
    "created_at",
}

ROOT = CurrentActor(
    user_id=1001,
    username="root",
    role_codes=frozenset({SUPER_ADMIN_ROLE_CODE}),
    data_scope=DataScope.ALL,
    ip="10.0.0.1",
    user_agent="pytest-root/1.0",
)


def _dept_admin(department_id: int = 2) -> CurrentActor:
    """部门管理员（非 DB 用户，避免自包含干扰 SUPER_ADMIN 计数）。"""
    return CurrentActor(
        user_id=7001,
        username="dept-admin",
        role_codes=frozenset({"DEPARTMENT_ADMIN"}),
        data_scope=DataScope.DEPARTMENT_CHILDREN,
        department_id=department_id,
        ip="10.0.0.9",
        user_agent="pytest-dept/1.0",
    )


async def _seed(session) -> None:
    """1 总部 / 2 研发（管理员在此）/ 3 前端 / 4 后端 / 5 市场。"""
    await make_department(session, department_id=1, department_code="HQ")
    await make_department(session, department_id=2, department_code="RD", parent_id=1)
    await make_department(session, department_id=3, department_code="RD-FE", parent_id=2)
    await make_department(session, department_id=4, department_code="RD-BE", parent_id=2)
    await make_department(session, department_id=5, department_code="MKT", parent_id=1)

    await make_role(session, role_id=SUPER_ROLE_ID, role_code=SUPER_ADMIN_ROLE_CODE)
    await make_role(session, role_id=DEPT_ADMIN_ROLE_ID, role_code="DEPARTMENT_ADMIN")
    await make_role(session, role_id=AUDITOR_ROLE_ID, role_code="AUDITOR")

    await make_user(session, user_id=2002, username="u-fe", department_id=3)
    await make_user(session, user_id=2004, username="u-mkt", department_id=5)


async def _make_super_admin(session, *, user_id: int, username: str, department_id: int) -> None:
    await make_user(session, user_id=user_id, username=username, department_id=department_id)
    await link_user_role(session, user_id=user_id, role_id=SUPER_ROLE_ID)


def _only_failure(recorder: RecordingAuditRecorder):
    """断言"恰好一条 FAILURE"，并返回它。

    为什么强调"恰好一条"：重复埋点会产生审计噪声，
    也会掩盖"同一拒绝被两层同时记录"的实现错误。
    """
    failures = recorder.failures()
    assert len(failures) == 1, f"期望恰好 1 条 FAILURE，实际 {len(failures)}：{recorder.actions()}"
    return failures[0]


# ---------------------------------------------------------------------------
# 用户侧：每一条拒绝路径
# ---------------------------------------------------------------------------
class TestUserDenialAudit:
    async def test_read_out_of_scope_is_audited(self, db_session) -> None:
        """读越权（GET /users/{id}）同样留痕。"""
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.get(actor=_dept_admin(), user_id=2004)

        event = _only_failure(recorder)
        assert event.action == AuditAction.USER_READ
        assert event.resource_id == 2004
        assert event.error_code == PERMISSION_DENIED

    async def test_update_other_department_user_is_audited(self, db_session) -> None:
        """FIX-002 用例 1：修改其他部门用户 → FAILURE。"""
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.update(actor=_dept_admin(), user_id=2004, display_name="越权改名")

        event = _only_failure(recorder)
        assert event.action == AuditAction.USER_UPDATE
        assert event.resource_type == "USER"
        assert event.resource_id == 2004
        assert event.error_code == PERMISSION_DENIED

    async def test_department_id_tamper_is_audited(self, db_session) -> None:
        """FIX-002 用例 2：把用户挪到范围外部门 → FAILURE。

        典型"改参数绕过数据范围"路径（Spec `10 §3`）。
        """
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.update(actor=_dept_admin(), user_id=2002, department_id=5)

        event = _only_failure(recorder)
        assert event.action == AuditAction.USER_UPDATE
        assert event.resource_id == 2002

    async def test_detach_user_from_department_is_audited(self, db_session) -> None:
        """非全局范围把用户移出部门（`department_id=None`）→ FAILURE。"""
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.update(actor=_dept_admin(), user_id=2002, department_id=None)

        assert _only_failure(recorder).action == AuditAction.USER_UPDATE

    async def test_disable_cross_scope_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.disable(actor=_dept_admin(), user_id=2004)

        event = _only_failure(recorder)
        assert event.action == AuditAction.USER_DISABLE
        assert event.resource_id == 2004

    async def test_enable_cross_scope_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.enable(actor=_dept_admin(), user_id=2004)

        assert _only_failure(recorder).action == AuditAction.USER_ENABLE

    async def test_delete_cross_scope_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.delete(actor=_dept_admin(), user_id=2004)

        event = _only_failure(recorder)
        assert event.action == AuditAction.USER_DELETE
        assert event.resource_id == 2004

    async def test_reset_password_cross_scope_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.reset_password(actor=_dept_admin(), user_id=2004, new_password=PW_A)

        assert _only_failure(recorder).action == AuditAction.USER_RESET_PASSWORD

    async def test_assign_roles_cross_scope_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.assign_roles(
                actor=_dept_admin(), user_id=2004, role_ids=frozenset({AUDITOR_ROLE_ID})
            )

        assert _only_failure(recorder).action == AuditAction.USER_ROLE_ASSIGN

    async def test_assign_privileged_role_is_audited(self, db_session) -> None:
        """FIX-002 用例 4：assign_roles 尝试授予 SUPER_ADMIN → FAILURE。"""
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError, match="SUPER_ADMIN"):
            await service.assign_roles(
                actor=_dept_admin(), user_id=2002, role_ids=frozenset({SUPER_ROLE_ID})
            )

        event = _only_failure(recorder)
        assert event.action == AuditAction.USER_ROLE_ASSIGN
        assert event.resource_id == 2002
        assert event.error_code == PERMISSION_DENIED

    async def test_create_with_privileged_role_is_audited(self, db_session) -> None:
        """FIX-002 用例 3：创建用户时尝试授予 SUPER_ADMIN → FAILURE。

        该提权发生在"部门范围校验已通过之后"，属于最容易被漏掉留痕的一类。
        """
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError, match="SUPER_ADMIN"):
            await service.create(
                actor=_dept_admin(),
                username="sneaky",
                password=PW_A,
                display_name="提权尝试",
                department_id=3,
                role_ids=frozenset({SUPER_ROLE_ID}),
            )

        event = _only_failure(recorder)
        assert event.action == AuditAction.USER_ROLE_ASSIGN
        assert event.resource_type == "USER"
        assert event.error_code == PERMISSION_DENIED

    async def test_create_out_of_scope_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.create(
                actor=_dept_admin(),
                username="outsider",
                password=PW_A,
                display_name="越权建号",
                department_id=5,
            )

        event = _only_failure(recorder)
        assert event.action == AuditAction.USER_CREATE
        assert event.resource_id is None

    async def test_operating_super_admin_is_audited(self, db_session) -> None:
        """非 SUPER_ADMIN 操作 SUPER_ADMIN → FAILURE（Spec 00 §1#7）。"""
        await _seed(db_session)
        await _make_super_admin(db_session, user_id=2010, username="rd-root", department_id=3)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError, match="SUPER_ADMIN"):
            await service.disable(actor=_dept_admin(), user_id=2010)

        assert _only_failure(recorder).action == AuditAction.USER_DISABLE

    async def test_success_path_records_no_failure(self, db_session) -> None:
        """反向对照：正常操作不得产生任何 FAILURE（避免"一律失败"的假通过）。"""
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        await service.disable(actor=_dept_admin(), user_id=2002)

        assert recorder.failures() == []
        assert recorder.find(str(AuditAction.USER_DISABLE)).result is AuditResult.SUCCESS


# ---------------------------------------------------------------------------
# 部门侧：含原先遗漏留痕的分支
# ---------------------------------------------------------------------------
class TestDepartmentDenialAudit:
    async def test_read_out_of_scope_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.get(actor=_dept_admin(), department_id=5)

        event = _only_failure(recorder)
        assert event.action == AuditAction.DEPARTMENT_READ
        assert event.resource_type == "DEPARTMENT"
        assert event.resource_id == 5

    async def test_create_root_without_global_scope_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.create(
                actor=_dept_admin(), department_code="NEW-ROOT", department_name="越权根"
            )

        event = _only_failure(recorder)
        assert event.action == AuditAction.DEPARTMENT_CREATE
        assert event.resource_id is None

    async def test_create_under_out_of_scope_parent_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.create(
                actor=_dept_admin(),
                department_code="X",
                department_name="越权子部门",
                parent_id=5,
            )

        event = _only_failure(recorder)
        assert event.action == AuditAction.DEPARTMENT_CREATE
        assert event.resource_id == 5

    async def test_move_to_root_without_global_scope_is_audited(self, db_session) -> None:
        """**原先遗漏留痕的分支**：非全局范围把部门移动到根层级。

        修复前该分支直接 `raise PermissionDeniedError` 而不写审计，
        是一条"可越权且不留痕"的盲区。
        """
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.update(actor=_dept_admin(), department_id=3, parent_id=None)

        event = _only_failure(recorder)
        assert event.action == AuditAction.DEPARTMENT_UPDATE
        assert event.resource_id == 3

    async def test_move_under_out_of_scope_parent_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.update(actor=_dept_admin(), department_id=3, parent_id=5)

        assert _only_failure(recorder).action == AuditAction.DEPARTMENT_UPDATE

    async def test_disable_out_of_scope_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.disable(actor=_dept_admin(), department_id=5)

        event = _only_failure(recorder)
        assert event.action == AuditAction.DEPARTMENT_DISABLE
        assert event.resource_id == 5

    async def test_delete_out_of_scope_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.delete(actor=_dept_admin(), department_id=5)

        assert _only_failure(recorder).action == AuditAction.DEPARTMENT_DELETE

    async def test_integrity_conflict_is_not_recorded_as_denial(self, db_session) -> None:
        """完整性拒绝（仍有子部门）不是越权，不得记成 FAILURE。

        与用户侧"最后一个 SUPER_ADMIN"形成对照：
        那个是**安全不变量**（必须留痕），这个是**业务规则冲突**（不留痕）。
        """
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        with pytest.raises(ConflictError):
            await service.delete(actor=ROOT, department_id=2)

        assert recorder.events == []


# ---------------------------------------------------------------------------
# RISK-002：最后一个 SUPER_ADMIN 是安全不变量
# ---------------------------------------------------------------------------
class TestLastSuperAdminInvariant:
    async def test_disable_last_super_admin_is_rejected_and_audited(self, db_session) -> None:
        await _seed(db_session)
        await _make_super_admin(db_session, user_id=2010, username="only-root", department_id=2)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(ConflictError, match="SUPER_ADMIN"):
            await service.disable(actor=ROOT, user_id=2010)

        event = _only_failure(recorder)
        assert event.action == AuditAction.USER_DISABLE
        assert event.resource_id == 2010
        assert event.error_code == CONFLICT

        target = await UserRepository(db_session).get(2010)
        assert target is not None and target.status is UserStatus.ACTIVE

    async def test_logical_delete_last_super_admin_is_rejected_and_audited(
        self, db_session
    ) -> None:
        await _seed(db_session)
        await _make_super_admin(db_session, user_id=2010, username="only-root", department_id=2)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(ConflictError, match="SUPER_ADMIN"):
            await service.delete(actor=ROOT, user_id=2010)

        event = _only_failure(recorder)
        assert event.action == AuditAction.USER_DELETE
        assert event.error_code == CONFLICT

        target = await UserRepository(db_session).get(2010)
        assert target is not None and target.deleted_at is None

    async def test_super_admin_actor_cannot_delete_self_as_last(self, db_session) -> None:
        """SUPER_ADMIN 自己也不能通过删除流程让系统失去唯一 SUPER_ADMIN。"""
        await _seed(db_session)
        await _make_super_admin(db_session, user_id=2010, username="only-root", department_id=2)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        self_actor = CurrentActor.super_admin(user_id=2010, username="only-root")

        with pytest.raises(ConflictError):
            await service.delete(actor=self_actor, user_id=2010)

        assert _only_failure(recorder).error_code == CONFLICT

    async def test_disable_allowed_when_another_super_admin_exists(self, db_session) -> None:
        """保留数量 > 1 时允许禁用，且只记 SUCCESS。"""
        await _seed(db_session)
        await _make_super_admin(db_session, user_id=2010, username="root-a", department_id=2)
        await _make_super_admin(db_session, user_id=2011, username="root-b", department_id=2)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        await service.disable(actor=ROOT, user_id=2010)

        assert recorder.failures() == []
        assert recorder.results() == ["SUCCESS"]

    async def test_soft_deleted_super_admin_does_not_count(self, db_session) -> None:
        """已逻辑删除的 SUPER_ADMIN 不计入保留数量。

        否则"先删一个、再删最后一个"会绕过不变量。
        """
        await _seed(db_session)
        await _make_super_admin(db_session, user_id=2010, username="gone-root", department_id=2)
        repository = UserRepository(db_session)
        assert await repository.count_super_admins() == 1

        target = await repository.get(2010)
        assert target is not None
        target.deleted_at = utc_now()
        await db_session.flush()

        assert await repository.count_super_admins() == 0

    async def test_disabled_super_admin_still_counts(self, db_session) -> None:
        """仅被禁用（未删除）的 SUPER_ADMIN 仍计入，避免"禁用绕删除"。"""
        await _seed(db_session)
        await _make_super_admin(db_session, user_id=2010, username="only-root", department_id=2)
        repository = UserRepository(db_session)

        target = await repository.get(2010)
        assert target is not None
        target.status = UserStatus.DISABLED
        await db_session.flush()

        assert await repository.count_super_admins() == 1


# ---------------------------------------------------------------------------
# 拒绝审计的字段完整性（FIX-002 明确要求的最小字段集）
# ---------------------------------------------------------------------------
class TestDenialEventFields:
    async def test_denial_event_carries_all_required_fields(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with (
            trace_context("trace-fix002", "req-fix002"),
            pytest.raises(PermissionDeniedError),
        ):
            await service.update(actor=_dept_admin(), user_id=2004, display_name="越权")

        event = _only_failure(recorder)
        assert event.operator_id == 7001
        assert event.operator_username == "dept-admin"
        assert event.action == AuditAction.USER_UPDATE
        assert event.resource_type == "USER"
        assert event.resource_id == 2004
        assert event.result is AuditResult.FAILURE
        assert event.error_code == PERMISSION_DENIED
        assert event.trace_id == "trace-fix002"
        assert event.request_id == "req-fix002"
        assert event.ip == "10.0.0.9"
        assert event.user_agent == "pytest-dept/1.0"
        assert isinstance(event.created_at, datetime)

    async def test_denial_event_has_no_before_after_payload(self, db_session) -> None:
        """被拒绝时不产生"变更前后"数据，避免审计里出现未发生的变更。"""
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        with pytest.raises(PermissionDeniedError):
            await service.update(actor=_dept_admin(), user_id=2004, display_name="越权")

        event = _only_failure(recorder)
        assert event.before_data is None
        assert event.after_data is None

    def test_audit_event_exposes_required_denial_fields(self) -> None:
        """FIX-002 要求的字段集必须真实存在于 `AuditEvent`。"""
        names = {f.name for f in fields(AuditEvent)}
        assert names >= REQUIRED_DENIAL_FIELDS
