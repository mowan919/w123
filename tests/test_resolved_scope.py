"""`ResolvedScope` fail-closed 不变量测试（unit）。

对应 Spec `11 §5` 取向："宁可拒绝，也不放行"。

`ResolvedScope` 是数据范围解析结果的载体。若允许构造出
"SELF 且 department_ids=None" 这类矛盾状态，下游 Repository 可能把它
解读为"部门维度不限制"，从而把"仅本人"放大为"全部可见" —— 典型越权。
因此这些不变量必须在构造时立刻抛错，而不是静默放行。

DD-19（多角色求并）补充
--------------------
多角色合并是新增的放大点：合并本身**只能放宽**，因此每条分支都必须
钉住"最宽的那一支"才算正确，且 `SELF ∪ 其他` 必须用 `include_self`
做**加法**，不能忽略 SELF（忽略等于把 SELF 当成不存在，
会让"只允许看自己"的角色在合并后失去意义）。
"""

from __future__ import annotations

import pytest

from app.core.scope import DataScope, ResolvedScope, RoleScopeConfig

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


# ===========================================================================
# DD-19：多角色数据范围求并
# ===========================================================================
class TestRoleScopeConfig:
    def test_custom_config_carries_department_set(self) -> None:
        config = RoleScopeConfig(
            role_id=1, data_scope=DataScope.CUSTOM, custom_department_ids=frozenset({5})
        )
        assert config.custom_department_ids == frozenset({5})

    def test_non_custom_with_departments_is_rejected(self) -> None:
        """非 CUSTOM 却带 CUSTOM 集合 = "以为已限定、实际未必"的陷阱。

        这种组合只可能来自"读取残留行后没有清理"，必须立刻失败而不是
        被静默忽略 —— 否则残留数据会以不可预期的方式参与范围计算。
        """
        with pytest.raises(ValueError, match="不得携带 custom_department_ids"):
            RoleScopeConfig(
                role_id=1,
                data_scope=DataScope.DEPARTMENT,
                custom_department_ids=frozenset({5}),
            )


class TestResolvedScopeMerge:
    def test_empty_input_is_rejected(self) -> None:
        """无角色 = 无范围来源，必须抛错而不是返回一个"看起来很安全"的对象。"""
        with pytest.raises(ValueError, match="无法合并空的数据范围集合"):
            ResolvedScope.merge([], actor_id=1)

    def test_single_scope_is_unchanged(self) -> None:
        """单角色合并结果必须与合并前逐字段等价（Phase 2 行为不回退）。"""
        original = ResolvedScope.for_departments(
            frozenset({2, 3}), scope=DataScope.DEPARTMENT_CHILDREN, actor_id=7
        )
        merged = ResolvedScope.merge([original], actor_id=7)
        assert merged.department_ids == frozenset({2, 3})
        assert merged.restrict_to_actor is False
        assert merged.include_self is False

    def test_any_all_produces_global(self) -> None:
        scopes = [
            ResolvedScope.for_departments(frozenset({2}), scope=DataScope.DEPARTMENT),
            ResolvedScope.global_scope(actor_id=7),
            ResolvedScope.self_only(actor_id=7),
        ]
        merged = ResolvedScope.merge(scopes, actor_id=7)
        assert merged.is_unrestricted_departments is True
        assert merged.department_ids is None

    def test_department_sets_are_unioned(self) -> None:
        scopes = [
            ResolvedScope.for_departments(frozenset({2, 3}), scope=DataScope.DEPARTMENT_CHILDREN),
            ResolvedScope.for_departments(frozenset({9}), scope=DataScope.CUSTOM),
        ]
        merged = ResolvedScope.merge(scopes, actor_id=7)
        assert merged.department_ids == frozenset({2, 3, 9})
        assert merged.source_scopes == frozenset({DataScope.DEPARTMENT_CHILDREN, DataScope.CUSTOM})

    def test_label_is_the_widest_source_scope(self) -> None:
        """标签只用于诊断，取最宽者，避免"实际很宽、标签写着 SELF"。"""
        scopes = [
            ResolvedScope.for_departments(frozenset({2}), scope=DataScope.DEPARTMENT),
            ResolvedScope.for_departments(frozenset({3}), scope=DataScope.CUSTOM),
        ]
        assert ResolvedScope.merge(scopes, actor_id=7).scope is DataScope.CUSTOM

    def test_all_self_stays_self_only(self) -> None:
        scopes = [ResolvedScope.self_only(actor_id=7), ResolvedScope.self_only(actor_id=7)]
        merged = ResolvedScope.merge(scopes, actor_id=7)
        assert merged.restrict_to_actor is True
        assert merged.include_self is True
        assert merged.department_ids == frozenset()

    def test_partial_self_adds_self_without_restricting(self) -> None:
        """`SELF ∪ 部门集合` = 部门集合 **外加** 本人（DD-19 关键分支）。

        不能简化为"忽略 SELF"：那会让 SELF 角色表达的"只允许看自己"
        在合并后失去意义；也不能简化为"仅本人"，那会缩小部门可见性。
        正确表达是"部门集合 ∪ {本人}"，即 `include_self`。
        """
        scopes = [
            ResolvedScope.self_only(actor_id=7),
            ResolvedScope.for_departments(frozenset({2, 3}), scope=DataScope.DEPARTMENT_CHILDREN),
        ]
        merged = ResolvedScope.merge(scopes, actor_id=7)
        assert merged.restrict_to_actor is False
        assert merged.include_self is True
        assert merged.department_ids == frozenset({2, 3})

    def test_no_self_source_means_include_self_false(self) -> None:
        scopes = [
            ResolvedScope.for_departments(frozenset({2}), scope=DataScope.DEPARTMENT),
            ResolvedScope.for_departments(frozenset({3}), scope=DataScope.CUSTOM),
        ]
        assert ResolvedScope.merge(scopes, actor_id=7).include_self is False

    def test_empty_department_sets_merge_to_empty(self) -> None:
        """全部来源都是空集合 → 结果仍是空集合（不会因为"合并"变成不限制）。"""
        scopes = [
            ResolvedScope.for_departments(frozenset(), scope=DataScope.CUSTOM),
            ResolvedScope.for_departments(frozenset(), scope=DataScope.DEPARTMENT),
        ]
        merged = ResolvedScope.merge(scopes, actor_id=7)
        assert merged.department_ids == frozenset()
        assert merged.denies_all_users is True


class TestIncludeSelfSemantics:
    """`include_self` 只做加法：增加"本人"这一条记录，绝不放宽部门维度。"""

    def test_include_self_requires_actor_id(self) -> None:
        with pytest.raises(ValueError, match="include_self=True 时必须提供 actor_id"):
            ResolvedScope(
                scope=DataScope.DEPARTMENT,
                department_ids=frozenset({2}),
                include_self=True,
                actor_id=None,
            )

    def test_allows_actor_outside_department_set(self) -> None:
        scope = ResolvedScope.for_departments(
            frozenset({2}), scope=DataScope.DEPARTMENT_CHILDREN, actor_id=7, include_self=True
        )
        # 本人在部门集合之外（department_id=None），仍必须被放行。
        assert scope.allows_user(user_id=7, department_id=None) is True

    def test_does_not_allow_other_users_outside_set(self) -> None:
        scope = ResolvedScope.for_departments(
            frozenset({2}), scope=DataScope.DEPARTMENT_CHILDREN, actor_id=7, include_self=True
        )
        assert scope.allows_user(user_id=8, department_id=None) is False
        assert scope.allows_user(user_id=8, department_id=99) is False

    def test_does_not_widen_department_dimension(self) -> None:
        scope = ResolvedScope.for_departments(
            frozenset({2}), scope=DataScope.DEPARTMENT_CHILDREN, actor_id=7, include_self=True
        )
        assert scope.allows_department(2) is True
        assert scope.allows_department(3) is False

    def test_denies_all_users_is_false_when_self_included(self) -> None:
        """空部门集合 + `include_self` → 本人仍可见，不能判成"谁都看不到"。"""
        scope = ResolvedScope.for_departments(
            frozenset(), scope=DataScope.CUSTOM, actor_id=7, include_self=True
        )
        assert scope.denies_all_departments is True
        assert scope.denies_all_users is False

    def test_restrict_to_actor_ignores_department_dimension(self) -> None:
        """SELF（仅本人）时部门条件不得叠加 —— 否则本人可能因部门不匹配被拒。"""
        scope = ResolvedScope.self_only(actor_id=7, department_ids=frozenset({2}))
        assert scope.allows_user(user_id=7, department_id=99) is True
        assert scope.allows_user(user_id=8, department_id=2) is False
