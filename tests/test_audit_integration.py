"""审计集成测试（integration + security）。

对应 Spec `06 §2`：审计必须包含 15 个字段
    audit_log_id / trace_id / request_id / operator_id / operator_username /
    action / resource_type / resource_id / before_data / after_data /
    result / error_code / ip / user_agent / created_at
对应 Spec `06 §3`：Trace 必须贯穿到 Audit（trace_id / request_id 自动携带）。
对应 Spec `10 §8`：关键安全操作必须可审计（含越权失败）。
对应 Spec `06 §4` / `10 §4`：before/after 脱敏，且**绝不**出现口令哈希。

Phase 2 只交付端口（`AuditRecorder`）；落库属 Phase 6。
本文件验证"每个业务操作都会经端口产出结构完整的事件"，
因此 Phase 6 替换实现时无需改动业务代码。
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from app.audit import AuditAction, AuditEvent, AuditResult
from app.auth.actor import SUPER_ADMIN_ROLE_CODE, CurrentActor
from app.core.context import trace_context
from app.core.errors import ConflictError, PermissionDeniedError
from app.core.scope import DataScope
from app.services.department import DepartmentService
from app.services.user import UserService
from tests.conftest import RecordingAuditRecorder
from tests.factories import link_user_role, make_department, make_role, make_user

pytestmark = pytest.mark.integration

SUPER_ROLE_ID = 9001
AUDITOR_ROLE_ID = 9003
ROOT = CurrentActor.super_admin(user_id=1001, username="root")
PW = "Alpha-Passw0rd!01"

#: Spec 06 §2 要求的 15 个字段。
REQUIRED_AUDIT_FIELDS = {
    "audit_log_id",
    "trace_id",
    "request_id",
    "operator_id",
    "operator_username",
    "action",
    "resource_type",
    "resource_id",
    "before_data",
    "after_data",
    "result",
    "error_code",
    "ip",
    "user_agent",
    "created_at",
}


def _dept_admin() -> CurrentActor:
    return CurrentActor(
        user_id=7001,
        username="dept-admin",
        role_codes=frozenset({"DEPARTMENT_ADMIN"}),
        data_scope=DataScope.DEPARTMENT_CHILDREN,
        department_id=2,
        ip="10.0.0.9",
        user_agent="pytest/1.0",
    )


async def _seed(session) -> None:
    await make_department(session, department_id=1, department_code="HQ")
    await make_department(session, department_id=2, department_code="RD", parent_id=1)
    await make_department(session, department_id=3, department_code="RD-FE", parent_id=2)
    # 4 是空叶子部门：无子部门、无在册用户 → 可被逻辑删除
    await make_department(session, department_id=4, department_code="RD-BE", parent_id=2)
    await make_department(session, department_id=5, department_code="MKT", parent_id=1)
    await make_role(session, role_id=SUPER_ROLE_ID, role_code=SUPER_ADMIN_ROLE_CODE)
    await make_role(session, role_id=AUDITOR_ROLE_ID, role_code="AUDITOR")
    await make_user(session, user_id=2002, username="u-fe", department_id=3)
    await make_user(session, user_id=2004, username="u-mkt", department_id=5)


class TestAuditEventShape:
    def test_event_carries_all_fifteen_spec_fields(self) -> None:
        names = {f.name for f in fields(AuditEvent)}
        assert names >= REQUIRED_AUDIT_FIELDS

    def test_build_fills_trace_and_request_id_from_context(self) -> None:
        with trace_context("trace-abc", "req-xyz"):
            event = AuditEvent.build(
                action=AuditAction.USER_CREATE,
                resource_type="USER",
                resource_id=1,
                operator_id=2,
                operator_username="root",
            )
        assert event.trace_id == "trace-abc"
        assert event.request_id == "req-xyz"

    def test_build_leaves_ids_none_outside_request_context(self) -> None:
        event = AuditEvent.build(
            action=AuditAction.USER_CREATE,
            resource_type="USER",
            resource_id=1,
            operator_id=2,
            operator_username="root",
        )
        assert event.trace_id is None
        assert event.request_id is None


class TestDepartmentAuditTrail:
    async def test_each_operation_records_expected_action(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)

        created = await service.create(
            actor=ROOT, department_code="RD-OPS", department_name="运维组", parent_id=2
        )
        await service.update(actor=ROOT, department_id=created.id, department_name="运维")
        await service.disable(actor=ROOT, department_id=created.id)

        assert recorder.actions() == [
            str(AuditAction.DEPARTMENT_CREATE),
            str(AuditAction.DEPARTMENT_UPDATE),
            str(AuditAction.DEPARTMENT_DISABLE),
        ]
        assert recorder.results() == ["SUCCESS", "SUCCESS", "SUCCESS"]
        assert all(event.resource_type == "DEPARTMENT" for event in recorder.events)

    async def test_delete_records_action_and_resource_id(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)
        await service.delete(actor=ROOT, department_id=4)
        event = recorder.find(str(AuditAction.DEPARTMENT_DELETE))
        assert event is not None
        assert event.resource_id == 4
        assert event.after_data["deleted_at"] is not None

    async def test_refused_delete_never_records_success(self, db_session) -> None:
        """删除被完整性约束拒绝时，绝不能留下 SUCCESS 审计。"""
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)
        with pytest.raises(ConflictError):
            await service.delete(actor=ROOT, department_id=3)
        assert all(event.result is not AuditResult.SUCCESS for event in recorder.events)

    async def test_denied_attempt_records_failure_with_error_code(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError):
            await service.create(
                actor=_dept_admin(), department_code="X", department_name="越权", parent_id=5
            )
        failures = recorder.failures()
        assert len(failures) == 1
        assert failures[0].action == AuditAction.DEPARTMENT_CREATE
        assert failures[0].error_code == 403001

    async def test_operator_ip_and_user_agent_are_carried(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = DepartmentService(db_session, audit=recorder)
        await service.disable(actor=_dept_admin(), department_id=3)
        event = recorder.find(str(AuditAction.DEPARTMENT_DISABLE))
        assert event is not None
        assert event.operator_id == 7001
        assert event.operator_username == "dept-admin"
        assert event.ip == "10.0.0.9"
        assert event.user_agent == "pytest/1.0"


class TestUserAuditTrail:
    async def test_every_mutating_operation_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        created = await service.create(
            actor=ROOT,
            username="newbie",
            password=PW,
            display_name="新人",
            department_id=2,
        )
        await service.update(actor=ROOT, user_id=created.id, display_name="新人甲")
        await service.disable(actor=ROOT, user_id=created.id)
        await service.enable(actor=ROOT, user_id=created.id)
        await service.reset_password(
            actor=ROOT, user_id=created.id, new_password="Bravo-Passw0rd!02"
        )
        await service.assign_roles(
            actor=ROOT, user_id=created.id, role_ids=frozenset({AUDITOR_ROLE_ID})
        )
        await service.delete(actor=ROOT, user_id=created.id)

        assert recorder.actions() == [
            str(AuditAction.USER_CREATE),
            str(AuditAction.USER_UPDATE),
            str(AuditAction.USER_DISABLE),
            str(AuditAction.USER_ENABLE),
            str(AuditAction.USER_RESET_PASSWORD),
            str(AuditAction.USER_ROLE_ASSIGN),
            str(AuditAction.USER_DELETE),
        ]
        assert all(event.resource_type == "USER" for event in recorder.events)
        assert all(event.result is AuditResult.SUCCESS for event in recorder.events)

    async def test_audit_never_contains_password_material(self, db_session) -> None:
        """Spec 10 §4：口令 / 口令哈希绝不进入审计。"""
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        created = await service.create(
            actor=ROOT, username="secretive", password=PW, display_name="保密", department_id=2
        )
        await service.reset_password(
            actor=ROOT, user_id=created.id, new_password="Bravo-Passw0rd!02"
        )

        dumped = str([(event.before_data, event.after_data) for event in recorder.events])
        assert PW not in dumped
        assert "Bravo-Passw0rd!02" not in dumped
        assert "password_hash" not in dumped
        assert "$argon2id$" not in dumped

    async def test_role_assignment_audit_has_before_and_after_ids(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        await service.assign_roles(actor=ROOT, user_id=2002, role_ids=frozenset({AUDITOR_ROLE_ID}))
        event = recorder.find(str(AuditAction.USER_ROLE_ASSIGN))
        assert event is not None
        assert event.before_data == {"role_ids": []}
        assert event.after_data == {"role_ids": [AUDITOR_ROLE_ID]}
        assert event.resource_id == 2002

    async def test_denied_cross_scope_attempt_is_audited(self, db_session) -> None:
        await _seed(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError):
            await service.update(actor=_dept_admin(), user_id=2004, display_name="越权")
        failures = recorder.failures()
        assert len(failures) == 1
        assert failures[0].action == AuditAction.USER_UPDATE
        assert failures[0].error_code == 403001
        assert failures[0].resource_id == 2004

    async def test_super_admin_protection_denial_is_audited(self, db_session) -> None:
        """非 SUPER_ADMIN 操作 SUPER_ADMIN → 必须留痕。"""
        await _seed(db_session)
        await make_user(db_session, user_id=2010, username="rd-root", department_id=3)
        await link_user_role(db_session, user_id=2010, role_id=SUPER_ROLE_ID)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError):
            await service.disable(actor=_dept_admin(), user_id=2010)
        failures = recorder.failures()
        assert len(failures) == 1
        assert failures[0].action == AuditAction.USER_DISABLE
        assert failures[0].result is AuditResult.FAILURE
