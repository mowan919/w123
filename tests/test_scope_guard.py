"""数据范围 → SQL 条件测试（integration + security）。

对应 Spec `10 §10`：带数据范围的查询必须在 Service / Repository 层真正约束，
**禁止**"先查询全部再在 Python 内存里过滤"。

本文件直接验证 `app/repositories/scope_filters.py` 的转换结果，
重点断言 fail-closed 不变量：
    空部门集合必须翻译为 SQL `FALSE`（查不到任何行），
    而不是"忽略条件"（那会把空范围放大为全局范围）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.scope import DataScope, ResolvedScope
from app.models.department import Department
from app.models.user import AdminUser
from app.repositories.scope_filters import department_scope_condition, user_scope_condition
from app.repositories.user import UserRepository
from tests.factories import make_department, make_user

pytestmark = pytest.mark.integration


async def _seed(session) -> None:
    await make_department(session, department_id=1, department_code="HQ")
    await make_department(session, department_id=2, department_code="RD", parent_id=1)
    await make_user(session, user_id=2001, username="u1", department_id=1)
    await make_user(session, user_id=2002, username="u2", department_id=2)
    await make_user(session, user_id=2003, username="u3", department_id=None)


async def _names_for_user_scope(session, scope: ResolvedScope) -> set[str]:
    stmt = select(AdminUser.username).where(user_scope_condition(scope))
    return set((await session.execute(stmt)).scalars().all())


class TestUserScopeCondition:
    async def test_global_scope_sees_all_rows(self, db_session) -> None:
        await _seed(db_session)
        names = await _names_for_user_scope(db_session, ResolvedScope.global_scope())
        assert names == {"u1", "u2", "u3"}

    async def test_department_scope_restricts_in_sql(self, db_session) -> None:
        await _seed(db_session)
        scope = ResolvedScope.for_departments(frozenset({2}), scope=DataScope.DEPARTMENT_CHILDREN)
        assert await _names_for_user_scope(db_session, scope) == {"u2"}

    @pytest.mark.security
    async def test_empty_department_scope_returns_no_rows(self, db_session) -> None:
        """fail-closed 核心：空集合 → FALSE，绝不退化为"全部可见"。"""
        await _seed(db_session)
        scope = ResolvedScope.for_departments(frozenset(), scope=DataScope.DEPARTMENT_CHILDREN)
        assert scope.denies_all_departments is True
        assert await _names_for_user_scope(db_session, scope) == set()

    @pytest.mark.security
    async def test_self_scope_returns_only_actor_without_widening_to_department(
        self, db_session
    ) -> None:
        """SELF 必须严格为 id = actor_id；不得与部门条件取并集。"""
        await _seed(db_session)
        scope = ResolvedScope.self_only(actor_id=2002, department_ids=frozenset({2}))
        assert await _names_for_user_scope(db_session, scope) == {"u2"}

    @pytest.mark.security
    async def test_self_scope_actor_in_busy_department_still_isolated(self, db_session) -> None:
        """同一部门有多个用户时，SELF 仍只返回本人。"""
        await _seed(db_session)
        await make_user(db_session, user_id=2004, username="u4", department_id=2)
        scope = ResolvedScope.self_only(actor_id=2002, department_ids=frozenset({2}))
        assert await _names_for_user_scope(db_session, scope) == {"u2"}


class TestDepartmentScopeCondition:
    async def test_department_scope_restricts_in_sql(self, db_session) -> None:
        await _seed(db_session)
        scope = ResolvedScope.for_departments(frozenset({2}), scope=DataScope.DEPARTMENT)
        stmt = select(Department.id).where(department_scope_condition(scope))
        assert set((await db_session.execute(stmt)).scalars().all()) == {2}

    async def test_empty_department_scope_yields_no_departments(self, db_session) -> None:
        await _seed(db_session)
        scope = ResolvedScope.for_departments(frozenset(), scope=DataScope.CUSTOM)
        stmt = select(Department.id).where(department_scope_condition(scope))
        assert set((await db_session.execute(stmt)).scalars().all()) == set()

    async def test_global_department_scope_returns_all(self, db_session) -> None:
        await _seed(db_session)
        stmt = select(Department.id).where(department_scope_condition(ResolvedScope.global_scope()))
        assert set((await db_session.execute(stmt)).scalars().all()) == {1, 2}


class TestRepositoryScopeIntegration:
    async def test_list_in_scope_excludes_departmentless_users_for_non_global(
        self, db_session
    ) -> None:
        await _seed(db_session)
        scope = ResolvedScope.for_departments(frozenset({1}), scope=DataScope.DEPARTMENT)
        users = await UserRepository(db_session).list_in_scope(scope, page_num=1, page_size=100)
        assert {user.username for user in users} == {"u1"}

    async def test_count_in_scope_matches_list(self, db_session) -> None:
        await _seed(db_session)
        scope = ResolvedScope.for_departments(
            frozenset({1, 2}), scope=DataScope.DEPARTMENT_CHILDREN
        )
        repo = UserRepository(db_session)
        users = await repo.list_in_scope(scope, page_num=1, page_size=100)
        total = await repo.count_in_scope(scope)
        assert total == len(users) == 2
