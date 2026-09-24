"""业务枚举。

Frozen 依据
-----------
- Spec `02 §3` 用户状态：至少 ACTIVE / DISABLED / LOCKED。
             （`DELETED` 不进入 status 枚举，逻辑删除统一由 `deleted_at` 表达，
              见 Spec `00 §6` / `07 §3`。）
- Spec `02 §1` 部门支持禁用 → DepartmentStatus 取 ACTIVE / DISABLED。
- Spec `03 §2` Role 含 status，未给定取值 → 取 ACTIVE / DISABLED。

注意：枚举值使用大写字符串，与 Spec 表述一致；Python 侧使用 `StrEnum`
以便直接参与 JSON 序列化与字符串比较。
"""

from __future__ import annotations

from enum import StrEnum


class DepartmentStatus(StrEnum):
    """部门状态。"""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class UserStatus(StrEnum):
    """用户状态。

    Spec `02 §3`：ACTIVE / DISABLED / LOCKED。
    LOCKED 与 `locked_until` 并存（02 §3 允许两者表达同一语义）。
    逻辑删除状态由 `deleted_at` 表达，不在本枚举内。
    """

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    LOCKED = "LOCKED"


class RoleStatus(StrEnum):
    """角色状态（本 Phase 只落库，不实现 Role 业务）。"""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


__all__ = ["DepartmentStatus", "RoleStatus", "UserStatus"]
