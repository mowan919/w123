"""用户服务测试（integration + security）。

对应 Verification `001-organization-user.md`：
    - 用户可以创建 / 修改 / 禁用 / 启用 / 逻辑删除
    - 用户与部门关联正确
    - 用户与角色可建立关联
    - 部门管理员只能管理范围内的用户（越权被拒）
    - 密码重置符合策略（历史不重复、重置后强制改密）

关键安全断言（Spec `10 §3` / `§10`）：
    - 越权读取 / 修改 / 删除一律 `PermissionDeniedError`；
    - 通过篡改 `department_id` 绕过数据范围的路径被堵死；
    - 保护生效在**服务层**，不依赖前端或 HTTP 层。
"""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import func, select

from app.audit import AuditAction
from app.auth.actor import SUPER_ADMIN_ROLE_CODE, CurrentActor
from app.core.errors import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.scope import DataScope
from app.core.security.password import get_password_hasher
from app.models.enums import UserStatus
from app.models.password_history import AdminUserPasswordHistory
from app.models.user import AdminUser
from app.repositories.role import RoleRepository
from app.services.user import UserService
from tests.conftest import RecordingAuditRecorder
from tests.factories import link_user_role, make_department, make_role, make_user

pytestmark = pytest.mark.integration

SUPER_ROLE_ID = 9001
DEPT_ADMIN_ROLE_ID = 9002
AUDITOR_ROLE_ID = 9003

#: 满足 Spec 00 §2 的强口令集合（互不相同）。
PW_A = "Alpha-Passw0rd!01"
PW_B = "Bravo-Passw0rd!02"
PW_C = "Charlie-Passw0rd!03"
PW_D = "Delta-Passw0rd!04"
PW_E = "Echo-Passw0rd!05"
PW_F = "Foxtrot-Passw0rd!06"
PW_G = "Golf-Passw0rd!07"

ROOT_ACTOR = CurrentActor.super_admin(user_id=1001, username="root")


def _dept_admin(
    department_id: int, *, scope: DataScope = DataScope.DEPARTMENT_CHILDREN
) -> CurrentActor:
    """部门管理员操作者（非 DB 用户，避免自包含干扰计数）。"""
    return CurrentActor(
        user_id=7001,
        username="dept-admin",
        role_codes=frozenset({"DEPARTMENT_ADMIN"}),
        data_scope=scope,
        department_id=department_id,
    )


async def _seed_tree(session) -> None:
    """部门树 + 普通用户 + 角色。

    1 总部
    ├── 2 研发中心        ← 部门管理员在这里
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

    await make_role(session, role_id=SUPER_ROLE_ID, role_code=SUPER_ADMIN_ROLE_CODE)
    await make_role(session, role_id=DEPT_ADMIN_ROLE_ID, role_code="DEPARTMENT_ADMIN")
    await make_role(session, role_id=AUDITOR_ROLE_ID, role_code="AUDITOR")

    await make_user(session, user_id=2001, username="u-rd", department_id=2)
    await make_user(session, user_id=2002, username="u-fe", department_id=3)
    await make_user(session, user_id=2003, username="u-be", department_id=4)
    await make_user(session, user_id=2004, username="u-mkt", department_id=5)
    await make_user(session, user_id=2005, username="u-sub", department_id=6)
    await make_user(session, user_id=2006, username="u-orphan", department_id=None)


async def _make_super_admin(
    session, *, user_id: int, username: str, department_id: int | None
) -> None:
    await make_user(session, user_id=user_id, username=username, department_id=department_id)
    await link_user_role(session, user_id=user_id, role_id=SUPER_ROLE_ID)


async def _history_count(session, user_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(AdminUserPasswordHistory)
        .where(AdminUserPasswordHistory.user_id == user_id)
    )
    return int((await session.execute(stmt)).scalar_one())


# ---------------------------------------------------------------------------
# 列表 / 数据范围
# ---------------------------------------------------------------------------
class TestUserListScope:
    async def test_super_admin_sees_all_users(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        page = await service.list_users(actor=ROOT_ACTOR, page_size=100)
        assert page.total == 6
        assert {user.username for user in page.items} == {
            "u-rd",
            "u-fe",
            "u-be",
            "u-mkt",
            "u-sub",
            "u-orphan",
        }

    async def test_department_admin_sees_only_subtree(self, db_session) -> None:
        """DEPARTMENT_CHILDREN：本部门 + 所有子部门（2、3、4）。"""
        await _seed_tree(db_session)
        service = UserService(db_session)
        page = await service.list_users(actor=_dept_admin(2), page_size=100)
        assert page.total == 3
        assert {user.username for user in page.items} == {"u-rd", "u-fe", "u-be"}

    async def test_user_without_department_is_invisible_to_department_admin(
        self, db_session
    ) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        page = await service.list_users(actor=_dept_admin(2), page_size=100)
        assert "u-orphan" not in {user.username for user in page.items}

    @pytest.mark.security
    async def test_out_of_scope_department_filter_yields_empty(self, db_session) -> None:
        """过滤条件与范围取交集：传范围外部门 ID 得到空，而不是越权数据。"""
        await _seed_tree(db_session)
        service = UserService(db_session)
        page = await service.list_users(actor=_dept_admin(2), department_id=5, page_size=100)
        assert page.total == 0
        assert page.items == []

    async def test_in_scope_department_filter_narrows_result(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        page = await service.list_users(actor=_dept_admin(2), department_id=3, page_size=100)
        assert page.total == 1
        assert page.items[0].username == "u-fe"

    async def test_status_filter(self, db_session) -> None:
        await _seed_tree(db_session)
        await make_user(
            db_session,
            user_id=2010,
            username="u-fe-off",
            department_id=3,
            status=UserStatus.DISABLED,
        )
        service = UserService(db_session)
        page = await service.list_users(
            actor=_dept_admin(2), status=UserStatus.DISABLED, page_size=100
        )
        assert {user.username for user in page.items} == {"u-fe-off"}

    async def test_keyword_filter_matches_username(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        page = await service.list_users(actor=_dept_admin(2), keyword="u-be", page_size=100)
        assert page.total == 1
        assert page.items[0].username == "u-be"

    async def test_pagination_total_is_scope_wide(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        page = await service.list_users(actor=_dept_admin(2), page_num=1, page_size=1)
        assert page.total == 3
        assert len(page.items) == 1
        assert page.page_num == 1
        assert page.page_size == 1

    async def test_deleted_users_are_excluded(self, db_session) -> None:
        """Spec 02 §5：逻辑删除后普通查询不得返回。"""
        await _seed_tree(db_session)
        service = UserService(db_session)
        await service.delete(actor=ROOT_ACTOR, user_id=2001)
        page = await service.list_users(actor=ROOT_ACTOR, page_size=100)
        assert "u-rd" not in {user.username for user in page.items}
        assert page.total == 5

    async def test_page_num_must_be_positive(self, db_session) -> None:
        service = UserService(db_session)
        with pytest.raises(BadRequestError, match="pageNum"):
            await service.list_users(actor=ROOT_ACTOR, page_num=0)

    async def test_page_size_upper_bound_enforced(self, db_session) -> None:
        service = UserService(db_session)
        with pytest.raises(BadRequestError, match="pageSize"):
            await service.list_users(actor=ROOT_ACTOR, page_size=101)

    async def test_self_scope_lists_only_actor(self, db_session) -> None:
        await _seed_tree(db_session)
        await make_user(db_session, user_id=3001, username="self-user", department_id=3)
        actor = CurrentActor(
            user_id=3001, username="self-user", data_scope=DataScope.SELF, department_id=3
        )
        page = await UserService(db_session).list_users(actor=actor, page_size=100)
        assert page.total == 1
        assert page.items[0].username == "self-user"


# ---------------------------------------------------------------------------
# 读取 / IDOR
# ---------------------------------------------------------------------------
class TestUserGetScope:
    async def test_super_admin_reads_any_user(self, db_session) -> None:
        await _seed_tree(db_session)
        user = await UserService(db_session).get(actor=ROOT_ACTOR, user_id=2005)
        assert user.username == "u-sub"

    async def test_department_admin_reads_in_scope_user(self, db_session) -> None:
        await _seed_tree(db_session)
        user = await UserService(db_session).get(actor=_dept_admin(2), user_id=2002)
        assert user.username == "u-fe"

    @pytest.mark.security
    async def test_read_out_of_scope_user_is_denied(self, db_session) -> None:
        await _seed_tree(db_session)
        with pytest.raises(PermissionDeniedError):
            await UserService(db_session).get(actor=_dept_admin(2), user_id=2004)

    @pytest.mark.security
    async def test_read_user_without_department_is_denied(self, db_session) -> None:
        await _seed_tree(db_session)
        with pytest.raises(PermissionDeniedError):
            await UserService(db_session).get(actor=_dept_admin(2), user_id=2006)

    @pytest.mark.security
    async def test_self_scope_cannot_read_others(self, db_session) -> None:
        await _seed_tree(db_session)
        await make_user(db_session, user_id=3001, username="self-user", department_id=3)
        actor = CurrentActor(
            user_id=3001, username="self-user", data_scope=DataScope.SELF, department_id=3
        )
        service = UserService(db_session)
        assert (await service.get(actor=actor, user_id=3001)).username == "self-user"
        with pytest.raises(PermissionDeniedError):
            await service.get(actor=actor, user_id=2002)

    async def test_missing_user_raises_not_found(self, db_session) -> None:
        await _seed_tree(db_session)
        with pytest.raises(NotFoundError):
            await UserService(db_session).get(actor=ROOT_ACTOR, user_id=999999)


# ---------------------------------------------------------------------------
# 创建
# ---------------------------------------------------------------------------
class TestUserCreate:
    async def test_super_admin_creates_user(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        user = await service.create(
            actor=ROOT_ACTOR,
            username="newbie",
            password=PW_A,
            display_name="新人",
            department_id=3,
        )
        assert user.id > 0
        assert user.status is UserStatus.ACTIVE
        assert user.must_change_password is True  # 管理员设初始口令 → 首登改密
        assert user.password_hash.startswith("$argon2id$")
        assert user.password_hash != PW_A
        assert recorder.actions() == [str(AuditAction.USER_CREATE)]
        assert recorder.results() == ["SUCCESS"]

    async def test_department_admin_creates_user_in_scope(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        user = await service.create(
            actor=_dept_admin(2),
            username="rd-new",
            password=PW_A,
            display_name="研发新人",
            department_id=3,
        )
        assert user.department_id == 3

    @pytest.mark.security
    async def test_department_admin_cannot_create_into_out_of_scope_department(
        self, db_session
    ) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError):
            await service.create(
                actor=_dept_admin(2),
                username="evil",
                password=PW_A,
                display_name="越权",
                department_id=5,
            )
        assert recorder.results() == ["FAILURE"]

    @pytest.mark.security
    async def test_non_global_actor_cannot_create_user_without_department(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        with pytest.raises(PermissionDeniedError):
            await service.create(
                actor=_dept_admin(2),
                username="no-dept",
                password=PW_A,
                display_name="无部门",
                department_id=None,
            )

    async def test_super_admin_may_create_user_without_department(self, db_session) -> None:
        await _seed_tree(db_session)
        user = await UserService(db_session).create(
            actor=ROOT_ACTOR,
            username="floating",
            password=PW_A,
            display_name="无部门",
        )
        assert user.department_id is None

    async def test_duplicate_username_is_conflict(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        with pytest.raises(ConflictError, match="已存在"):
            await service.create(
                actor=ROOT_ACTOR,
                username="u-rd",
                password=PW_A,
                display_name="重复",
                department_id=2,
            )

    async def test_weak_password_is_rejected(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        with pytest.raises(BadRequestError, match="密码"):
            await service.create(
                actor=ROOT_ACTOR,
                username="weakling",
                password="short",
                display_name="弱口令",
                department_id=2,
            )

    async def test_create_with_roles(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        user = await service.create(
            actor=ROOT_ACTOR,
            username="auditor1",
            password=PW_A,
            display_name="审计员",
            department_id=2,
            role_ids=frozenset({AUDITOR_ROLE_ID}),
        )
        roles = await service.list_roles(actor=ROOT_ACTOR, user_id=user.id)
        assert [role.id for role in roles] == [AUDITOR_ROLE_ID]

    async def test_create_with_unknown_role_is_bad_request(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        with pytest.raises(BadRequestError, match="角色"):
            await service.create(
                actor=ROOT_ACTOR,
                username="badrole",
                password=PW_A,
                display_name="坏角色",
                department_id=2,
                role_ids=frozenset({999999}),
            )

    @pytest.mark.security
    async def test_department_admin_cannot_create_super_admin(self, db_session) -> None:
        """提权防护：创建用户时附带 SUPER_ADMIN 角色必须被拒。"""
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError):
            await service.create(
                actor=_dept_admin(2),
                username="escalate",
                password=PW_A,
                display_name="提权",
                department_id=3,
                role_ids=frozenset({SUPER_ROLE_ID}),
            )
        assert recorder.results() == ["FAILURE"]

    async def test_audit_snapshot_masks_contact_and_hides_password(self, db_session) -> None:
        """Spec 00 §8 / 10 §4：审计快照脱敏手机 / 邮箱，且不含任何口令字段。"""
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        await service.create(
            actor=ROOT_ACTOR,
            username="contact",
            password=PW_A,
            display_name="联系人",
            department_id=2,
            phone="13800001234",
            email="abc@example.com",
        )
        event = recorder.find(str(AuditAction.USER_CREATE))
        assert event is not None
        after = event.after_data
        assert after["phone"] == "138****1234"
        assert after["email"] == "abc***@example.com"
        assert "password_hash" not in after
        assert "password" not in after


# ---------------------------------------------------------------------------
# 修改
# ---------------------------------------------------------------------------
class TestUserUpdate:
    async def test_update_display_name_and_contact(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        updated = await service.update(
            actor=ROOT_ACTOR,
            user_id=2002,
            display_name="前端组员",
            phone="13900005678",
        )
        assert updated.display_name == "前端组员"
        assert updated.phone == "13900005678"
        event = recorder.find(str(AuditAction.USER_UPDATE))
        assert event is not None
        assert event.before_data["display_name"] == "u-fe"
        assert event.after_data["display_name"] == "前端组员"

    async def test_update_cannot_change_status(self, db_session) -> None:
        """状态变更必须走专用操作，以保证审计动作不可绕过。"""
        await _seed_tree(db_session)
        updated = await UserService(db_session).update(
            actor=ROOT_ACTOR, user_id=2002, display_name="仅改名"
        )
        assert updated.status is UserStatus.ACTIVE

    async def test_update_username_conflict(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        with pytest.raises(ConflictError, match="已存在"):
            await service.update(actor=ROOT_ACTOR, user_id=2002, username="u-be")

    async def test_update_department_within_scope(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        updated = await service.update(actor=_dept_admin(2), user_id=2002, department_id=4)
        assert updated.department_id == 4

    @pytest.mark.security
    async def test_cannot_move_user_into_out_of_scope_department(self, db_session) -> None:
        """篡改 department_id 试图把用户挪出范围 → 拒绝。"""
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError):
            await service.update(actor=_dept_admin(2), user_id=2002, department_id=5)
        # 事务内用户未被改动
        assert (await service.get(actor=_dept_admin(2), user_id=2002)).department_id == 3
        assert recorder.results() == ["FAILURE"]

    @pytest.mark.security
    async def test_non_global_actor_cannot_detach_user_from_department(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        with pytest.raises(PermissionDeniedError):
            await service.update(actor=_dept_admin(2), user_id=2002, department_id=None)

    @pytest.mark.security
    async def test_cannot_update_out_of_scope_user(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError):
            await service.update(actor=_dept_admin(2), user_id=2004, display_name="越权")
        assert recorder.results() == ["FAILURE"]

    @pytest.mark.security
    async def test_non_super_admin_cannot_update_super_admin_in_scope(self, db_session) -> None:
        await _seed_tree(db_session)
        await _make_super_admin(db_session, user_id=2010, username="rd-root", department_id=3)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError, match="SUPER_ADMIN"):
            await service.update(actor=_dept_admin(2), user_id=2010, display_name="篡改")
        assert recorder.results() == ["FAILURE"]


# ---------------------------------------------------------------------------
# 禁用 / 启用
# ---------------------------------------------------------------------------
class TestUserStatus:
    async def test_disable_and_enable(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        disabled = await service.disable(actor=ROOT_ACTOR, user_id=2002)
        assert disabled.status is UserStatus.DISABLED
        enabled = await service.enable(actor=ROOT_ACTOR, user_id=2002)
        assert enabled.status is UserStatus.ACTIVE
        assert recorder.actions() == [
            str(AuditAction.USER_DISABLE),
            str(AuditAction.USER_ENABLE),
        ]

    async def test_disabled_user_still_listed(self, db_session) -> None:
        """禁用不是删除：仍应出现在列表中。"""
        await _seed_tree(db_session)
        service = UserService(db_session)
        await service.disable(actor=ROOT_ACTOR, user_id=2002)
        page = await service.list_users(actor=_dept_admin(2), page_size=100)
        assert "u-fe" in {user.username for user in page.items}

    @pytest.mark.security
    async def test_department_admin_cannot_disable_super_admin(self, db_session) -> None:
        await _seed_tree(db_session)
        await _make_super_admin(db_session, user_id=2010, username="rd-root", department_id=3)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError, match="SUPER_ADMIN"):
            await service.disable(actor=_dept_admin(2), user_id=2010)
        assert recorder.results() == ["FAILURE"]

    async def test_cannot_disable_last_super_admin(self, db_session) -> None:
        await _seed_tree(db_session)
        await _make_super_admin(db_session, user_id=2010, username="root-2", department_id=1)
        service = UserService(db_session)
        # 唯一未删除的 SUPER_ADMIN → 保护
        with pytest.raises(ConflictError, match="SUPER_ADMIN"):
            await service.disable(actor=ROOT_ACTOR, user_id=2010)

    async def test_can_disable_super_admin_when_another_exists(self, db_session) -> None:
        await _seed_tree(db_session)
        await _make_super_admin(db_session, user_id=2010, username="root-a", department_id=1)
        await _make_super_admin(db_session, user_id=2011, username="root-b", department_id=1)
        service = UserService(db_session)
        disabled = await service.disable(actor=ROOT_ACTOR, user_id=2010)
        assert disabled.status is UserStatus.DISABLED


# ---------------------------------------------------------------------------
# 逻辑删除
# ---------------------------------------------------------------------------
class TestUserLogicalDelete:
    async def test_delete_sets_disabled_and_deleted_at(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        deleted = await service.delete(actor=ROOT_ACTOR, user_id=2002)
        assert deleted.status is UserStatus.DISABLED
        assert deleted.deleted_at is not None
        assert recorder.actions() == [str(AuditAction.USER_DELETE)]

    async def test_deleted_user_is_not_readable(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        await service.delete(actor=ROOT_ACTOR, user_id=2002)
        with pytest.raises(NotFoundError):
            await service.get(actor=ROOT_ACTOR, user_id=2002)

    async def test_username_reusable_after_delete(self, db_session) -> None:
        """软删除感知唯一性：删除后可用同一登录名重建。"""
        await _seed_tree(db_session)
        service = UserService(db_session)
        await service.delete(actor=ROOT_ACTOR, user_id=2002)
        recreated = await service.create(
            actor=ROOT_ACTOR,
            username="u-fe",
            password=PW_A,
            display_name="重建",
            department_id=3,
        )
        assert recreated.id != 2002
        assert recreated.username == "u-fe"

    @pytest.mark.security
    async def test_cannot_delete_out_of_scope_user(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError):
            await service.delete(actor=_dept_admin(2), user_id=2005)
        assert recorder.results() == ["FAILURE"]

    async def test_cannot_delete_last_super_admin(self, db_session) -> None:
        await _seed_tree(db_session)
        await _make_super_admin(db_session, user_id=2010, username="root-2", department_id=1)
        service = UserService(db_session)
        with pytest.raises(ConflictError, match="SUPER_ADMIN"):
            await service.delete(actor=ROOT_ACTOR, user_id=2010)


# ---------------------------------------------------------------------------
# 密码重置
# ---------------------------------------------------------------------------
class TestUserPasswordReset:
    async def _new_user(self, session, recorder: RecordingAuditRecorder) -> AdminUser:
        await _seed_tree(session)
        return await UserService(session, audit=recorder).create(
            actor=ROOT_ACTOR,
            username="pw-user",
            password=PW_A,
            display_name="改密用户",
            department_id=3,
        )

    async def test_reset_changes_hash_and_forces_change(self, db_session) -> None:
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        user = await self._new_user(db_session, recorder)
        old_hash = user.password_hash

        updated = await service.reset_password(actor=ROOT_ACTOR, user_id=user.id, new_password=PW_B)
        assert updated.password_hash != old_hash
        assert get_password_hasher().verify(PW_B, updated.password_hash) is True
        assert updated.must_change_password is True
        assert updated.password_changed_at is not None
        assert await _history_count(db_session, user.id) == 1
        assert recorder.find(str(AuditAction.USER_RESET_PASSWORD)) is not None

    async def test_reset_rejects_weak_password(self, db_session) -> None:
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        user = await self._new_user(db_session, recorder)
        with pytest.raises(BadRequestError, match="密码"):
            await service.reset_password(actor=ROOT_ACTOR, user_id=user.id, new_password="weak")

    async def test_reset_rejects_current_password(self, db_session) -> None:
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        user = await self._new_user(db_session, recorder)
        with pytest.raises(BadRequestError, match="当前密码"):
            await service.reset_password(actor=ROOT_ACTOR, user_id=user.id, new_password=PW_A)

    async def test_reset_rejects_password_from_history(self, db_session) -> None:
        """Spec 00 §2：最近 5 个密码不可重复。"""
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        user = await self._new_user(db_session, recorder)

        await service.reset_password(actor=ROOT_ACTOR, user_id=user.id, new_password=PW_B)
        # PW_A 已进入历史 → 不可复用
        with pytest.raises(BadRequestError, match="最近"):
            await service.reset_password(actor=ROOT_ACTOR, user_id=user.id, new_password=PW_A)

    async def test_password_history_is_capped(self, db_session) -> None:
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        user = await self._new_user(db_session, recorder)

        for candidate in (PW_B, PW_C, PW_D, PW_E, PW_F, PW_G):
            await service.reset_password(actor=ROOT_ACTOR, user_id=user.id, new_password=candidate)

        assert await _history_count(db_session, user.id) == 5

    @pytest.mark.security
    async def test_cannot_reset_out_of_scope_user_password(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError):
            await service.reset_password(actor=_dept_admin(2), user_id=2005, new_password=PW_B)
        assert recorder.results() == ["FAILURE"]

    @pytest.mark.security
    async def test_non_super_admin_cannot_reset_super_admin_password(self, db_session) -> None:
        await _seed_tree(db_session)
        await _make_super_admin(db_session, user_id=2010, username="rd-root", department_id=3)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError, match="SUPER_ADMIN"):
            await service.reset_password(actor=_dept_admin(2), user_id=2010, new_password=PW_B)
        assert recorder.results() == ["FAILURE"]


# ---------------------------------------------------------------------------
# 角色关联
# ---------------------------------------------------------------------------
class TestUserRoleAssignment:
    async def test_assign_roles_replaces_existing(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)

        before, after = await service.assign_roles(
            actor=ROOT_ACTOR, user_id=2002, role_ids=frozenset({AUDITOR_ROLE_ID})
        )
        assert before == frozenset()
        assert after == frozenset({AUDITOR_ROLE_ID})
        assert [role.id for role in await service.list_roles(actor=ROOT_ACTOR, user_id=2002)] == [
            AUDITOR_ROLE_ID
        ]

        before2, after2 = await service.assign_roles(
            actor=ROOT_ACTOR, user_id=2002, role_ids=frozenset({DEPT_ADMIN_ROLE_ID})
        )
        assert before2 == frozenset({AUDITOR_ROLE_ID})
        assert after2 == frozenset({DEPT_ADMIN_ROLE_ID})

        event = recorder.find(str(AuditAction.USER_ROLE_ASSIGN))
        assert event is not None
        assert event.before_data == {"role_ids": []}
        assert event.after_data == {"role_ids": [AUDITOR_ROLE_ID]}

    async def test_assign_empty_set_clears_roles(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        await service.assign_roles(
            actor=ROOT_ACTOR, user_id=2002, role_ids=frozenset({AUDITOR_ROLE_ID})
        )
        _, after = await service.assign_roles(actor=ROOT_ACTOR, user_id=2002, role_ids=frozenset())
        assert after == frozenset()
        assert await service.list_roles(actor=ROOT_ACTOR, user_id=2002) == []

    async def test_assign_unknown_role_is_bad_request(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        with pytest.raises(BadRequestError, match="角色"):
            await service.assign_roles(actor=ROOT_ACTOR, user_id=2002, role_ids=frozenset({999999}))

    @pytest.mark.security
    async def test_non_super_admin_cannot_grant_super_admin(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError, match="SUPER_ADMIN"):
            await service.assign_roles(
                actor=_dept_admin(2), user_id=2002, role_ids=frozenset({SUPER_ROLE_ID})
            )
        assert recorder.results() == ["FAILURE"]

    @pytest.mark.security
    async def test_non_super_admin_cannot_change_roles_of_super_admin(self, db_session) -> None:
        """特权账户的角色不可被普通管理员改动（含撤销路径）。"""
        await _seed_tree(db_session)
        await _make_super_admin(db_session, user_id=2010, username="rd-root", department_id=3)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError):
            await service.assign_roles(actor=_dept_admin(2), user_id=2010, role_ids=frozenset())
        assert recorder.results() == ["FAILURE"]

    async def test_super_admin_can_grant_super_admin(self, db_session) -> None:
        await _seed_tree(db_session)
        service = UserService(db_session)
        _, after = await service.assign_roles(
            actor=ROOT_ACTOR, user_id=2002, role_ids=frozenset({SUPER_ROLE_ID})
        )
        assert after == frozenset({SUPER_ROLE_ID})

    async def test_role_change_takes_effect_immediately(self, db_session) -> None:
        """Spec 00 §1：权限即时生效（同一会话内角色可立即读到）。"""
        await _seed_tree(db_session)
        service = UserService(db_session)
        await service.assign_roles(
            actor=ROOT_ACTOR, user_id=2002, role_ids=frozenset({AUDITOR_ROLE_ID})
        )
        codes = await RoleRepository(db_session).list_role_codes_for_user(2002)
        assert "AUDITOR" in codes

    @pytest.mark.security
    async def test_cannot_assign_roles_to_out_of_scope_user(self, db_session) -> None:
        await _seed_tree(db_session)
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        with pytest.raises(PermissionDeniedError):
            await service.assign_roles(
                actor=_dept_admin(2), user_id=2005, role_ids=frozenset({AUDITOR_ROLE_ID})
            )
        assert recorder.results() == ["FAILURE"]


# ---------------------------------------------------------------------------
# RISK-001：创建必须改密 + 本人改密后解除强制
# ---------------------------------------------------------------------------
class TestMustChangePasswordLifecycle:
    """`must_change_password` 必须是一个**可双向切换**的状态。

    若只能置 True 而不能置 False，Spec `00 §2` 的"管理员重置后首次登录
    必须修改密码"就变成永久锁死 —— 因此本用例集同时钉住两个方向。
    """

    async def _create(self, session, recorder: RecordingAuditRecorder | None = None) -> AdminUser:
        await _seed_tree(session)
        service = UserService(session, audit=recorder or RecordingAuditRecorder())
        return await service.create(
            actor=ROOT_ACTOR,
            username="fresh",
            password=PW_A,
            display_name="新人",
            department_id=3,
        )

    @staticmethod
    def _self_actor(user_id: int) -> CurrentActor:
        return CurrentActor(
            user_id=user_id,
            username="fresh",
            department_id=3,
            data_scope=DataScope.SELF,
        )

    async def test_created_user_must_change_password(self, db_session) -> None:
        """RISK-001：管理员创建用户 = 管理员设置初始口令 → 强制改密。"""
        user = await self._create(db_session)
        assert user.must_change_password is True

    async def test_created_user_is_active_and_unlocked(self, db_session) -> None:
        """初始状态必须是"可用"：ACTIVE、失败计数 0、未锁定。"""
        user = await self._create(db_session)
        assert user.status is UserStatus.ACTIVE
        assert user.failed_login_count == 0
        assert user.locked_until is None
        assert user.password_changed_at is not None

    async def test_self_change_clears_must_change_flag(self, db_session) -> None:
        """RISK-001：本人完成改密 → `must_change_password = False`。"""
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        user = await self._create(db_session, recorder)
        assert user.must_change_password is True

        updated = await service.change_own_password(
            actor=self._self_actor(user.id),
            current_password=PW_A,
            new_password=PW_B,
        )

        assert updated.must_change_password is False
        assert get_password_hasher().verify(PW_B, updated.password_hash) is True
        assert recorder.find(str(AuditAction.USER_CHANGE_PASSWORD)) is not None
        assert recorder.failures() == []

    async def test_self_change_records_old_password_into_history(self, db_session) -> None:
        """改密同样受"最近 5 个不可重复"约束，因此旧口令必须入历史。"""
        service = UserService(db_session)
        user = await self._create(db_session)
        actor = self._self_actor(user.id)

        await service.change_own_password(actor=actor, current_password=PW_A, new_password=PW_B)

        assert await _history_count(db_session, user.id) == 1
        with pytest.raises(BadRequestError, match="最近"):
            await service.change_own_password(actor=actor, current_password=PW_B, new_password=PW_A)

    async def test_reset_password_re_arms_forced_change(self, db_session) -> None:
        """管理员重置 → 重新置 True（与创建同一意图，保持一致）。"""
        service = UserService(db_session)
        user = await self._create(db_session)
        await service.change_own_password(
            actor=self._self_actor(user.id), current_password=PW_A, new_password=PW_B
        )
        assert user.must_change_password is False

        await service.reset_password(actor=ROOT_ACTOR, user_id=user.id, new_password=PW_C)
        assert user.must_change_password is True

    @pytest.mark.security
    async def test_wrong_current_password_is_denied_and_audited(self, db_session) -> None:
        recorder = RecordingAuditRecorder()
        service = UserService(db_session, audit=recorder)
        user = await self._create(db_session, recorder)
        recorder.events.clear()

        with pytest.raises(PermissionDeniedError, match="当前口令"):
            await service.change_own_password(
                actor=self._self_actor(user.id), current_password=PW_B, new_password=PW_C
            )

        failures = recorder.failures()
        assert len(failures) == 1
        assert failures[0].action == AuditAction.USER_CHANGE_PASSWORD
        # 口令未被修改，强制改密标记保持
        assert user.must_change_password is True
        assert get_password_hasher().verify(PW_A, user.password_hash) is True

    async def test_weak_new_password_is_rejected(self, db_session) -> None:
        service = UserService(db_session)
        user = await self._create(db_session)

        with pytest.raises(BadRequestError, match="密码"):
            await service.change_own_password(
                actor=self._self_actor(user.id), current_password=PW_A, new_password="weak"
            )
        assert user.must_change_password is True

    async def test_cannot_reuse_current_password(self, db_session) -> None:
        service = UserService(db_session)
        user = await self._create(db_session)

        with pytest.raises(BadRequestError, match="当前密码"):
            await service.change_own_password(
                actor=self._self_actor(user.id), current_password=PW_A, new_password=PW_A
            )

    @pytest.mark.security
    async def test_self_change_has_no_target_user_parameter(self) -> None:
        """IDOR 的结构性消除：签名里**没有** `user_id`。

        目标恒为 `actor.user_id`，因此无法构造出"改他人密码"的调用 ——
        这比"运行时校验 user_id"更彻底（后者总有漏判风险）。
        """
        params = set(inspect.signature(UserService.change_own_password).parameters)
        assert "user_id" not in params
        assert params == {"self", "actor", "current_password", "new_password"}
