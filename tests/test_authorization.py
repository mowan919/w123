"""集中式授权边界测试（integration + security）。

对应 Spec `10 §3`：SUPER_ADMIN 相关 bypass 必须集中封装，
普通管理员不得通过修改参数绕过；且提权路径（授予 SUPER_ADMIN）必须封死。
对应 Spec `00 §1#7` / `15 D-007`：其他管理员不能操作 SUPER_ADMIN。

本文件只测 `AuthorizationService`，不经过 HTTP 层，
以证明保护发生在**服务层**而非依赖前端隐藏。
"""

from __future__ import annotations

import pytest

from app.auth.actor import SUPER_ADMIN_ROLE_CODE, CurrentActor
from app.core.errors import ConflictError, PermissionDeniedError
from app.core.scope import DataScope
from app.models.user import AdminUser
from app.repositories.user import UserRepository
from app.services.authorization import AuthorizationService
from tests.factories import link_user_role, make_role, make_user

pytestmark = pytest.mark.integration

SUPER_ROLE_ID = 9001
NORMAL_ROLE_ID = 9002
OTHER_ROLE_ID = 9003


async def _get_user(session, user_id: int) -> AdminUser:
    user = await UserRepository(session).get(user_id)
    assert user is not None, f"fixture user {user_id} 不存在"
    return user


async def _seed_roles_and_users(session) -> None:
    """构造：1 个 SUPER_ADMIN 用户、1 个普通用户、3 个角色。"""
    await make_role(session, role_id=SUPER_ROLE_ID, role_code=SUPER_ADMIN_ROLE_CODE)
    await make_role(session, role_id=NORMAL_ROLE_ID, role_code="DEPARTMENT_ADMIN")
    await make_role(session, role_id=OTHER_ROLE_ID, role_code="AUDITOR")

    await make_user(session, user_id=1001, username="root")
    await link_user_role(session, user_id=1001, role_id=SUPER_ROLE_ID)

    await make_user(session, user_id=1002, username="normal")
    await link_user_role(session, user_id=1002, role_id=NORMAL_ROLE_ID)


def _dept_admin_actor() -> CurrentActor:
    return CurrentActor(
        user_id=1002,
        username="normal",
        role_codes=frozenset({"DEPARTMENT_ADMIN"}),
        data_scope=DataScope.DEPARTMENT_CHILDREN,
        department_id=1,
    )


class TestIsSuperAdminUser:
    async def test_detects_super_admin_by_role_code(self, db_session) -> None:
        await _seed_roles_and_users(db_session)
        authz = AuthorizationService(db_session)
        assert await authz.is_super_admin_user(1001) is True
        assert await authz.is_super_admin_user(1002) is False

    async def test_unknown_user_is_not_super_admin(self, db_session) -> None:
        await _seed_roles_and_users(db_session)
        assert await AuthorizationService(db_session).is_super_admin_user(999999) is False


class TestCanManageUser:
    async def test_super_admin_can_manage_anyone(self, db_session) -> None:
        await _seed_roles_and_users(db_session)
        authz = AuthorizationService(db_session)
        root = CurrentActor.super_admin(user_id=1001, username="root")
        # 不抛异常即通过
        await authz.assert_can_manage_user(actor=root, target=await _get_user(db_session, 1001))
        await authz.assert_can_manage_user(actor=root, target=await _get_user(db_session, 1002))

    async def test_admin_can_manage_normal_user(self, db_session) -> None:
        await _seed_roles_and_users(db_session)
        authz = AuthorizationService(db_session)
        await authz.assert_can_manage_user(
            actor=_dept_admin_actor(), target=await _get_user(db_session, 1002)
        )

    @pytest.mark.security
    async def test_non_super_admin_cannot_manage_super_admin(self, db_session) -> None:
        """越权核心：普通管理员不得触碰 SUPER_ADMIN。"""
        await _seed_roles_and_users(db_session)
        authz = AuthorizationService(db_session)
        with pytest.raises(PermissionDeniedError, match="SUPER_ADMIN"):
            await authz.assert_can_manage_user(
                actor=_dept_admin_actor(), target=await _get_user(db_session, 1001)
            )


class TestCanAssignRoles:
    async def test_super_admin_can_grant_super_admin_role(self, db_session) -> None:
        await _seed_roles_and_users(db_session)
        authz = AuthorizationService(db_session)
        await authz.assert_can_assign_roles(
            actor=CurrentActor.super_admin(user_id=1001, username="root"),
            role_ids=frozenset({SUPER_ROLE_ID}),
        )

    @pytest.mark.security
    async def test_non_super_admin_cannot_grant_super_admin_role(self, db_session) -> None:
        """提权防护：非 SUPER_ADMIN 不得授予 SUPER_ADMIN。"""
        await _seed_roles_and_users(db_session)
        authz = AuthorizationService(db_session)
        with pytest.raises(PermissionDeniedError, match="SUPER_ADMIN"):
            await authz.assert_can_assign_roles(
                actor=_dept_admin_actor(), role_ids=frozenset({SUPER_ROLE_ID})
            )

    async def test_non_super_admin_can_assign_non_privileged_roles(self, db_session) -> None:
        await _seed_roles_and_users(db_session)
        authz = AuthorizationService(db_session)
        await authz.assert_can_assign_roles(
            actor=_dept_admin_actor(), role_ids=frozenset({OTHER_ROLE_ID})
        )

    async def test_empty_role_set_is_always_allowed(self, db_session) -> None:
        await _seed_roles_and_users(db_session)
        authz = AuthorizationService(db_session)
        await authz.assert_can_assign_roles(actor=_dept_admin_actor(), role_ids=frozenset())


class TestNotLastSuperAdmin:
    async def test_single_super_admin_is_protected(self, db_session) -> None:
        await _seed_roles_and_users(db_session)
        authz = AuthorizationService(db_session)
        with pytest.raises(ConflictError, match="SUPER_ADMIN"):
            await authz.assert_not_last_super_admin(target=await _get_user(db_session, 1001))

    async def test_two_super_admins_allow_disable(self, db_session) -> None:
        await _seed_roles_and_users(db_session)
        await make_user(db_session, user_id=1003, username="root2")
        await link_user_role(db_session, user_id=1003, role_id=SUPER_ROLE_ID)
        authz = AuthorizationService(db_session)
        await authz.assert_not_last_super_admin(target=await _get_user(db_session, 1001))

    async def test_normal_user_is_not_protected(self, db_session) -> None:
        await _seed_roles_and_users(db_session)
        authz = AuthorizationService(db_session)
        await authz.assert_not_last_super_admin(target=await _get_user(db_session, 1002))
