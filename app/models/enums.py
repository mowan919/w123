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


class PermissionResourceType(StrEnum):
    """权限资源类型（Phase 3 / DD-20 已冻结）。

    依据 Spec `00 §3` / `03 §5~§9` 的五段权限链：
        Page / Menu / Button / API / Field
    """

    PAGE = "PAGE"
    MENU = "MENU"
    BUTTON = "BUTTON"
    API = "API"
    FIELD = "FIELD"


class PermissionStatus(StrEnum):
    """权限资源状态。

    Spec 未单独规定资源状态取值，故复用业务表统一的 ACTIVE / DISABLED
    语义（与 `RoleStatus` 一致）。DISABLED 的资源不参与有效权限计算。
    """

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class FieldAccessLevel(StrEnum):
    """字段权限等级（Spec `03 §9` / `00 §3`）。

    四级取值直接来自冻结 Spec，不可增删。

    合并序（DD-06 已冻结：**最宽松者胜**）::

        HIDDEN < READ_ONLY < VISIBLE < EDITABLE

    注意：该方向与 `00 §1#2`"权限取并集"同向，因此 `HIDDEN`
    **不能**覆盖其他角色授予的 `VISIBLE`。若要"HIDDEN 一票否决"
    必须由人类重新裁定（见 `docs/DESIGN-DECISIONS.md` DD-06）。
    """

    HIDDEN = "HIDDEN"
    READ_ONLY = "READ_ONLY"
    VISIBLE = "VISIBLE"
    EDITABLE = "EDITABLE"

    @property
    def rank(self) -> int:
        """合并用的序（越大越宽松）。"""
        return _FIELD_ACCESS_RANK[self]


#: 字段等级 → 合并序。集中一处，避免比较逻辑散落。
_FIELD_ACCESS_RANK: dict[FieldAccessLevel, int] = {
    FieldAccessLevel.HIDDEN: 0,
    FieldAccessLevel.READ_ONLY: 1,
    FieldAccessLevel.VISIBLE: 2,
    FieldAccessLevel.EDITABLE: 3,
}

#: 字段等级中"可以读到值"的集合（HIDDEN 之外都可以读）。
#: 供 Phase 8 输出字段策略时判断"是否应下发该字段"。
FIELD_ACCESS_READABLE: frozenset[FieldAccessLevel] = frozenset(
    {
        FieldAccessLevel.READ_ONLY,
        FieldAccessLevel.VISIBLE,
        FieldAccessLevel.EDITABLE,
    }
)

#: 字段等级中"可以写入"的集合。
FIELD_ACCESS_WRITABLE: frozenset[FieldAccessLevel] = frozenset({FieldAccessLevel.EDITABLE})


def most_permissive_field_level(
    levels: list[FieldAccessLevel] | tuple[FieldAccessLevel, ...] | frozenset[FieldAccessLevel],
) -> FieldAccessLevel | None:
    """按 DD-06 冻结的"最宽松者胜"合并字段等级。空输入返回 None。"""
    if not levels:
        return None
    return max(levels, key=lambda level: level.rank)


class HttpMethod(StrEnum):
    """API 资源支持的 HTTP 方法（DD-20 已冻结的取值域）。"""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


__all__ = [
    "FIELD_ACCESS_READABLE",
    "FIELD_ACCESS_WRITABLE",
    "DepartmentStatus",
    "FieldAccessLevel",
    "HttpMethod",
    "PermissionResourceType",
    "PermissionStatus",
    "RoleStatus",
    "UserStatus",
    "most_permissive_field_level",
]
