"""数据范围（Data Scope）。

Frozen 依据
-----------
- Spec `03 §10` 支持 ALL / DEPARTMENT / DEPARTMENT_CHILDREN / SELF / CUSTOM。
- Spec `00 §1#1` / `15 D-001` 部门管理员默认 = 本部门 + 所有子部门。
- Spec `10 §10` 所有带数据范围的查询必须在 Service/Repository 层真正约束；
  禁止"先查询全部再在 Python 内存中过滤"。
- Spec `11 §5`（缓存安全取向）："宁可 cache miss，也不能用过期权限放行"
  —— 同一取向要求范围解析失败时按**拒绝**处理。

设计说明
-------
`DataScope` 是**授权策略**（角色维度配置的值）；
`ResolvedScope` 是**已解析的查询约束**（可直接下推到 SQL）。

关键不变量（fail-closed）
------------------------
只有 ALL 允许 `department_ids is None`（表示部门维度不限制）。
其余策略一律携带**具体集合**；空集合表示"无任何可见部门"，
Repository 必须翻译为 `FALSE` 条件，而不是忽略该条件。

该不变量在 `__post_init__` 中强制校验：一旦有人构造出
"SELF 且 department_ids=None"，会立刻抛错而不是静默放行 ——
这堵住了"范围解析失败退化为全局"这类典型越权路径。

CUSTOM 范围说明
--------------
`03 §10` 定义了 CUSTOM，但 `16 §34#7`（DD-07）明确 **CUSTOM 的存储模型尚未冻结**。
因此本模块只提供 CUSTOM 的**算法支持**（由调用方传入部门 ID 集合），
**不实现任何存储**。CUSTOM 的持久化必须等 DD-07 冻结后再做。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DataScope(StrEnum):
    """角色配置的数据范围策略（Spec 03 §10）。"""

    ALL = "ALL"
    DEPARTMENT = "DEPARTMENT"
    DEPARTMENT_CHILDREN = "DEPARTMENT_CHILDREN"
    SELF = "SELF"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    """已解析的数据范围约束，供 Repository 下推到 SQL。

    Attributes:
        scope: 来源策略，仅用于诊断与审计。
        actor_id: 当前操作者用户 ID；`restrict_to_actor` 为真时用于用户维度过滤。
        department_ids: 允许访问的部门 ID 集合。
            **None 仅允许出现在 ALL**；空集合表示不可见任何部门。
        restrict_to_actor: 用户维度是否必须限定为 actor 本人（SELF）。
    """

    scope: DataScope
    actor_id: int | None = None
    department_ids: frozenset[int] | None = None
    restrict_to_actor: bool = False

    def __post_init__(self) -> None:
        if self.department_ids is None and self.scope is not DataScope.ALL:
            raise ValueError(
                f"fail-closed：scope={self.scope.value} 不允许 department_ids=None "
                "（只有 ALL 表示部门维度不限制）。请传入具体部门集合，空集合表示无可见部门。"
            )
        if self.restrict_to_actor and self.actor_id is None:
            raise ValueError("fail-closed：restrict_to_actor=True 时必须提供 actor_id。")
        if self.scope is DataScope.SELF and not self.restrict_to_actor:
            raise ValueError("fail-closed：SELF 策略必须设置 restrict_to_actor=True。")

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------
    @classmethod
    def global_scope(cls, *, actor_id: int | None = None) -> ResolvedScope:
        """全局范围：部门维度与用户维度均不限制（仅 SUPER_ADMIN / ALL）。"""
        return cls(scope=DataScope.ALL, actor_id=actor_id, department_ids=None)

    @classmethod
    def for_departments(
        cls,
        department_ids: frozenset[int],
        *,
        scope: DataScope = DataScope.DEPARTMENT_CHILDREN,
        actor_id: int | None = None,
    ) -> ResolvedScope:
        """限定到给定部门集合（空集合 = 什么都看不到）。"""
        if scope is DataScope.ALL:
            raise ValueError("ALL 不允许指定部门集合；请使用 global_scope()。")
        return cls(scope=scope, actor_id=actor_id, department_ids=department_ids)

    @classmethod
    def self_only(
        cls,
        *,
        actor_id: int,
        department_ids: frozenset[int] | None = None,
    ) -> ResolvedScope:
        """仅本人。

        Args:
            actor_id: 操作者 ID。
            department_ids: 操作者所属部门（可含后代）。
                为 None 时按**空集合**处理，即部门维度什么都看不到 ——
                fail-closed，绝不退化为全局。
        """
        ids = department_ids if department_ids is not None else frozenset()
        return cls(
            scope=DataScope.SELF,
            actor_id=actor_id,
            department_ids=ids,
            restrict_to_actor=True,
        )

    # ------------------------------------------------------------------
    # 判定
    # ------------------------------------------------------------------
    @property
    def is_unrestricted_departments(self) -> bool:
        """部门维度是否不施加条件（仅 ALL）。"""
        return self.department_ids is None

    @property
    def denies_all_departments(self) -> bool:
        """是否为"空范围"：无任何可见部门。

        fail-closed 关键路径：必须翻译为 SQL `FALSE`，而非忽略条件。
        """
        return self.department_ids is not None and len(self.department_ids) == 0

    def allows_department(self, department_id: int) -> bool:
        """目标部门是否落在本范围内。

        用于**服务端二次校验**：防止操作者通过修改请求体中的
        `department_id` 绕过自己的数据范围（Spec 10 §3）。

        注意：DEPARTMENT_CHILDREN 的解析结果已包含全部后代，
        因此这里是纯集合判定，无需再查数据库。
        """
        if self.is_unrestricted_departments:
            return True
        if self.department_ids is None:  # pragma: no cover - 由不变量保证不可达
            return False
        return department_id in self.department_ids


__all__ = ["DataScope", "ResolvedScope"]
