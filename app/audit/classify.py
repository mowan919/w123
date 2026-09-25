"""审计动作 → 日志类别（Spec `06 §1` 的五类日志如何分流）。

为什么需要一张显式的分类表
-------------------------
`06 §1` 把日志分成五类，却没有给出"哪个动作属于哪一类"的清单。
如果不把映射写死在一个地方，就会出现两种真实问题：

1. 同一个动作在不同写入点被分到不同类别 → 检索时漏记录；
2. 新加一个 `AuditAction` 却没人想起来给它分类 → 它**静默地**只进审计表，
   永远不出现在安全日志里，而运维不会发现"安全日志少了一类事件"。

因此本模块：

- 用**三个封闭集合**覆盖全部 `AuditAction`；
- 另有一个测试断言 `SECURITY ∪ OPERATION ∪ READ_ONLY == set(AuditAction)`，
  于是"新增动作忘了分类"会在 CI 里**立刻失败**，而不是无声地漏日志。

三类而不是两类
-------------
`operation_logs` 的定位是"普通业务操作"（`06 §1`），即**改变状态**的操作。
只读操作既不是安全事件，也不是"业务操作"，因此单列 `READ_ONLY`：
它们**只进审计表**。这样做的依据是 `06 §1` 对 Audit Log 的定义 ——
"高价值业务变更**与管理员行为**"：管理员查看他人数据属"管理员行为"，
必须留痕（Phase 2~5 已按此口径登记 `USER_READ` / `DEPARTMENT_READ` /
`ROLE_READ` / `SESSION_READ` 等），但把它塞进"业务操作"会让
`operation_logs` 变成读日志，与 `06 §1` 的措辞不符。

登记为 INTERIM：Spec 未枚举动作与类别的对应关系，本表是技术默认。
"""

from __future__ import annotations

from enum import StrEnum

from app.audit.events import AuditAction


class LogCategory(StrEnum):
    """一条审计事件在 `06 §1` 五类日志中的归属。"""

    #: 安全事件 → `audit_logs` + `security_logs`（180 天）。
    SECURITY = "SECURITY"
    #: 业务操作 → `audit_logs` + `operation_logs`（180 天）。
    OPERATION = "OPERATION"
    #: 只读行为 → **仅** `audit_logs`（2 年）。
    READ_ONLY = "READ_ONLY"


#: `04 §8` 的安全日志清单覆盖的类别：登录 / 锁定 / MFA / 密码 / Session / 安全事件。
#:
#: 为什么 `USER_RESET_PASSWORD` / `USER_CHANGE_PASSWORD` 在这里：
#: `04 §8` 明确要求记录 "password reset / password change"；
#: Phase 4 已裁定它们**复用** Phase 2 的两个动作（不新增同义事件），
#: 因此这两个动作必须归入安全类，否则 `04 §8` 的密码事件就没有落点。
SECURITY_ACTIONS: frozenset[AuditAction] = frozenset(
    {
        AuditAction.AUTH_LOGIN_SUCCESS,
        AuditAction.AUTH_LOGIN_FAILURE,
        AuditAction.AUTH_LOCKOUT,
        AuditAction.AUTH_LOGOUT,
        AuditAction.AUTH_TOKEN_REUSE_DETECTED,
        AuditAction.AUTH_SESSION_REVOKE,
        AuditAction.MFA_SETUP,
        AuditAction.MFA_ENABLE,
        AuditAction.MFA_DISABLE,
        AuditAction.MFA_FAILURE,
        AuditAction.USER_RESET_PASSWORD,
        AuditAction.USER_CHANGE_PASSWORD,
        # `04 §8` 的 "Session"：会话元数据（IP / UA）属敏感读取面，
        # 与"谁被踢下线"必须能对称回答（Phase 5 已据此登记该动作）。
        AuditAction.SESSION_READ,
    }
)

#: 只读行为：只进审计表，不进 `operation_logs`（见模块文档）。
READ_ONLY_ACTIONS: frozenset[AuditAction] = frozenset(
    {
        AuditAction.USER_READ,
        AuditAction.DEPARTMENT_READ,
        AuditAction.ROLE_READ,
        AuditAction.ROLE_DATA_SCOPE_READ,
        AuditAction.ROLE_PERMISSION_READ,
        AuditAction.PERMISSION_RESOURCE_READ,
        AuditAction.PERMISSION_PREVIEW,
    }
)

#: 普通业务操作：改变状态的业务写入。
OPERATION_ACTIONS: frozenset[AuditAction] = frozenset(
    {
        AuditAction.USER_CREATE,
        AuditAction.USER_UPDATE,
        AuditAction.USER_DISABLE,
        AuditAction.USER_ENABLE,
        AuditAction.USER_DELETE,
        AuditAction.USER_ROLE_ASSIGN,
        AuditAction.DEPARTMENT_CREATE,
        AuditAction.DEPARTMENT_UPDATE,
        AuditAction.DEPARTMENT_DISABLE,
        AuditAction.DEPARTMENT_DELETE,
        AuditAction.ROLE_CREATE,
        AuditAction.ROLE_UPDATE,
        AuditAction.ROLE_DELETE,
        AuditAction.ROLE_DATA_SCOPE_UPDATE,
        AuditAction.ROLE_PERMISSION_UPDATE,
        AuditAction.ROLE_INHERITANCE_GRANT,
        AuditAction.ROLE_INHERITANCE_REVOKE,
        AuditAction.PERMISSION_RESOURCE_CREATE,
        AuditAction.PERMISSION_RESOURCE_UPDATE,
        AuditAction.PERMISSION_RESOURCE_DELETE,
    }
)


def classify(action: AuditAction) -> LogCategory:
    """返回动作所属类别。

    Raises:
        KeyError: 动作未被分类（**不可达**：三个集合已被测试断言覆盖全集）。
            这里刻意用异常而不是"回落到 OPERATION" ——
            静默回落正是"新动作漏分类"得以长期存活的原因。

    """
    if action in SECURITY_ACTIONS:
        return LogCategory.SECURITY
    if action in READ_ONLY_ACTIONS:
        return LogCategory.READ_ONLY
    if action in OPERATION_ACTIONS:
        return LogCategory.OPERATION
    raise KeyError(f"审计动作未分类：{action}")


__all__ = [
    "OPERATION_ACTIONS",
    "READ_ONLY_ACTIONS",
    "SECURITY_ACTIONS",
    "LogCategory",
    "classify",
]
