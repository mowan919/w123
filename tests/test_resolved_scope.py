"""`ResolvedScope` fail-closed 不变量测试（unit）。

对应 Spec `11 §5` 取向："宁可拒绝，也不放行"。

`ResolvedScope` 是数据范围解析结果的载体。若允许构造出
"SELF 且 department_ids=None" 这类矛盾状态，下游 Repository 可能把它
解读为"部门维度不限制"，从而把"仅本人"放大为"全部可见" —— 典型越权。
因此这些不变量必须在构造时立刻抛错，而不是静默放行。
"""

from __future__ import annotations

import pytest

from app.core.scope import DataScope, ResolvedScope

pytestmark = pytest.mark.unit


class TestResolvedScopeInvariants:
    def test_non_all_scope_requires_department_set(self) -> None:
        with pytest.raises(ValueError, match="department_ids=None"):
            ResolvedScope(scope=DataScope.DEPARTMENT_CHILDREN, department_ids=None)

    def test_self_scope_requires_restrict_to_actor(self) -> None:
        with pytest.raises(ValueError, match="restrict_to_actor"):
            ResolvedScope(scope=DataScope.SELF, department_ids=frozenset())

    def test_restrict_to_actor_requires_actor_id(self) -> None:
        with pytest.raises(ValueError, match="actor_id"):
            ResolvedScope(
                scope=DataScope.SELF,
                department_ids=frozenset(),
                restrict_to_actor=True,
                actor_id=None,
            )

    def test_all_scope_must_not_pass_department_set(self) -> None:
        with pytest.raises(ValueError, match="ALL"):
            ResolvedScope.for_departments(frozenset({1}), scope=DataScope.ALL)

    def test_only_all_allows_none_department_ids(self) -> None:
        scope = ResolvedScope.global_scope()
        assert scope.department_ids is None
        assert scope.is_unrestricted_departments is True
        assert scope.denies_all_departments is False


class TestResolvedScopeSemantics:
    def test_empty_department_set_is_deny_all(self) -> None:
        scope = ResolvedScope.for_departments(frozenset(), scope=DataScope.DEPARTMENT)
        assert scope.denies_all_departments is True
        assert scope.is_unrestricted_departments is False

    def test_allows_department_membership(self) -> None:
        scope = ResolvedScope.for_departments(
            frozenset({2, 3}), scope=DataScope.DEPARTMENT_CHILDREN
        )
        assert scope.allows_department(2) is True
        assert scope.allows_department(3) is True
        assert scope.allows_department(5) is False

    def test_global_allows_every_department(self) -> None:
        scope = ResolvedScope.global_scope()
        assert scope.allows_department(999) is True

    def test_empty_scope_allows_nothing(self) -> None:
        scope = ResolvedScope.for_departments(frozenset(), scope=DataScope.CUSTOM)
        assert scope.allows_department(1) is False

    def test_self_only_keeps_actor_and_does_not_grant_departments(self) -> None:
        scope = ResolvedScope.self_only(actor_id=42, department_ids=frozenset({7}))
        assert scope.restrict_to_actor is True
        assert scope.actor_id == 42
        assert scope.department_ids == frozenset({7})

    def test_self_only_without_department_is_empty_not_none(self) -> None:
        """未传部门 → 空集合（不是 None，绝不放宽为全局）。"""
        scope = ResolvedScope.self_only(actor_id=42)
        assert scope.department_ids == frozenset()
        assert scope.is_unrestricted_departments is False
        assert scope.denies_all_departments is True
