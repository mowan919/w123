"""审计动作 → 日志类别的分流（Spec `06 §1`）。

这一组测试的真正价值不是"`classify` 返回值对不对"，而是**第一条**：

    新增一个 `AuditAction` 却忘了分类 → 测试立刻失败。

`06 §1` 把日志分成五类，却没有给出"哪个动作属于哪一类"的清单。
没有这条断言，漏分类的后果是**静默的**：动作照常进审计表，
却永远不会出现在安全日志里，而运维不会发现"安全日志少了一类事件"。
"""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest

from app.audit.classify import (
    OPERATION_ACTIONS,
    READ_ONLY_ACTIONS,
    SECURITY_ACTIONS,
    LogCategory,
    classify,
)
from app.audit.events import AuditAction


class TestClassificationCoversEveryAction:
    """三个集合必须**恰好**划分全部 `AuditAction`。"""

    def test_union_covers_every_action(self) -> None:
        covered = SECURITY_ACTIONS | OPERATION_ACTIONS | READ_ONLY_ACTIONS
        missing = set(AuditAction) - covered
        assert missing == set(), f"以下审计动作未分类：{sorted(str(a) for a in missing)}"

    def test_sets_are_pairwise_disjoint(self) -> None:
        assert frozenset() == SECURITY_ACTIONS & OPERATION_ACTIONS
        assert frozenset() == SECURITY_ACTIONS & READ_ONLY_ACTIONS
        assert frozenset() == OPERATION_ACTIONS & READ_ONLY_ACTIONS

    def test_no_unknown_action_in_the_sets(self) -> None:
        """集合里不得出现已删除的动作（否则是死配置）。"""
        known = set(AuditAction)
        for group in (SECURITY_ACTIONS, OPERATION_ACTIONS, READ_ONLY_ACTIONS):
            assert group <= known


class TestClassify:
    """逐类抽查。"""

    @pytest.mark.parametrize(
        "action",
        [
            AuditAction.AUTH_LOGIN_SUCCESS,
            AuditAction.AUTH_LOCKOUT,
            AuditAction.AUTH_TOKEN_REUSE_DETECTED,
            AuditAction.MFA_FAILURE,
            AuditAction.USER_RESET_PASSWORD,
            AuditAction.SESSION_READ,
        ],
    )
    def test_security_actions(self, action: AuditAction) -> None:
        assert classify(action) is LogCategory.SECURITY

    @pytest.mark.parametrize(
        "action",
        [
            AuditAction.USER_CREATE,
            AuditAction.ROLE_PERMISSION_UPDATE,
            AuditAction.DEPARTMENT_DELETE,
            AuditAction.PERMISSION_RESOURCE_CREATE,
        ],
    )
    def test_operation_actions(self, action: AuditAction) -> None:
        assert classify(action) is LogCategory.OPERATION

    @pytest.mark.parametrize(
        "action",
        [
            AuditAction.USER_READ,
            AuditAction.ROLE_DATA_SCOPE_READ,
            AuditAction.PERMISSION_PREVIEW,
        ],
    )
    def test_read_only_actions(self, action: AuditAction) -> None:
        assert classify(action) is LogCategory.READ_ONLY

    def test_unknown_action_raises_instead_of_falling_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """刻意用异常：静默回落到 OPERATION 正是"漏分类"得以长期存活的原因。"""
        module = importlib.import_module("app.audit.classify")
        monkeypatch.setattr(module, "SECURITY_ACTIONS", frozenset())
        monkeypatch.setattr(module, "OPERATION_ACTIONS", frozenset())
        monkeypatch.setattr(module, "READ_ONLY_ACTIONS", frozenset())
        with pytest.raises(KeyError):
            classify(AuditAction.AUTH_LOGIN_SUCCESS)


class TestPackageNamespaceDoesNotShadowSubmodules:
    """`app.audit` 不得把与子模块同名的函数重导出。

    `classify` 既是子模块名（`app.audit.classify`）又是其中的函数名。
    包 `__init__` 一旦重导出该函数，`app.audit.classify` 这个属性就从模块
    变成函数，于是所有**按点号字符串定位**的工具（`pytest` 的
    `monkeypatch.setattr("app.audit.classify.X", ...)`、`mock.patch`）全部解析失败。

    这个错误只在特定 import 顺序下暴露：`sys.modules` 里仍是模块，
    `importlib.import_module` 一切正常，只有 `getattr` 路径受影响 ——
    因此它必须由一条**专门**的断言钉住，而不是靠"测试碰巧跑到"。
    """

    def test_app_audit_classify_is_the_module(self) -> None:
        import app.audit

        attribute = app.audit.classify
        assert isinstance(attribute, ModuleType), (
            f"app.audit.classify 变成了 {type(attribute).__name__}：包 __init__ 重导出遮蔽了子模块"
        )

    def test_string_targeted_patching_works(self) -> None:
        """真实复现失败的用法（本 Phase 的完整测试运行确实因此失败过）。"""
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr("app.audit.classify.OPERATION_ACTIONS", frozenset())
        assert classify(AuditAction.USER_CREATE) is LogCategory.OPERATION


class TestPasswordEventsAreSecurityEvents:
    """`04 §8` 的 "password reset / password change" 必须落在安全日志。"""

    def test_both_password_actions_are_security(self) -> None:
        assert AuditAction.USER_RESET_PASSWORD in SECURITY_ACTIONS
        assert AuditAction.USER_CHANGE_PASSWORD in SECURITY_ACTIONS

    def test_read_actions_never_enter_operation_log(self) -> None:
        """只读行为不进 `operation_logs`：它是"业务操作"，不是"查看"。"""
        assert READ_ONLY_ACTIONS.isdisjoint(OPERATION_ACTIONS)
