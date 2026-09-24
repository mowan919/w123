"""数据范围（Data Scope）。

Frozen 依据
-----------
- Spec `03 §10` 支持 ALL / DEPARTMENT / DEPARTMENT_CHILDREN / SELF / CUSTOM。
- Spec `00 §1#1` / `15 D-001` 部门管理员默认 = 本部门 + 所有子部门。
- Spec `00 §1#2` / `15 D-002`：多角色权限**取并集**。
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
1. 只有 ALL 允许 `department_ids is None`（表示部门维度不限制）。
   其余策略一律携带**具体集合**；空集合表示"无任何可见部门"，
   Repository 必须翻译为 `FALSE` 条件，而不是忽略该条件。
2. `restrict_to_actor=True`（SELF）时用户维度严格限定为操作者本人。
3. `include_self=True` 需要 `actor_id`（否则无从表达"本人"）。

这些不变量在 `__post_init__` 中强制校验：一旦有人构造出
"SELF 且 department_ids=None"，会立刻抛错而不是静默放行 ——
这堵住了"范围解析失败退化为全局"这类典型越权路径。

多角色合并（DD-19 已冻结：**求并 / 最宽**）
----------------------------------------
用户可持有多个角色（`00 §1#2`），每个角色各带一个 `data_scope`。
Spec 只冻结了"权限取并集"，未规定数据范围如何合并 ——
DD-19 经人类裁定采用**可见集合求并**（最宽），理由是与 `00 §1#2`
的并集方向一致、可解释性最好。规则：

```text
ALL               ∪ 任意   = ALL（全局）
DEPARTMENT_CHILDREN(d) ∪ CUSTOM{c} = {d 及后代} ∪ {c}
SELF              ∪ 其他   = 其他可见集合 **外加** actor 本人
```

第三种情形需要 `include_self` 表达 —— 既有的 `restrict_to_actor` 是
"**仅**本人"语义，**无法**表达"部门集合 ∪ 本人"。因此本模块新增
`include_self` 字段：它只**增加**本人这一条记录，从不放宽部门维度。

CUSTOM 范围说明
--------------
`03 §10` 定义了 CUSTOM，DD-07 已冻结其存储模型
（`roles.data_scope` 列 + `role_custom_scope_departments` 子表）。
本模块只负责**算法**（由调用方传入部门 ID 集合），
存储与读取由 `RoleDataScopeService` / `RoleRepository` 承担。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class DataScope(StrEnum):
    """角色配置的数据范围策略（Spec 03 §10）。"""

    ALL = "ALL"
    DEPARTMENT = "DEPARTMENT"
    DEPARTMENT_CHILDREN = "DEPARTMENT_CHILDREN"
    SELF = "SELF"
    CUSTOM = "CUSTOM"


#: 合并结果的"代表策略"优先级（越靠后越宽）。
#:
#: `ResolvedScope.scope` 仅用于**诊断与审计**（真正的判权依据是
#: `department_ids` / `restrict_to_actor` / `include_self` 三个字段）。
#: 多角色合并后可能同时来自多个策略，此时取其中**最宽**的一个作为代表，
#: 避免出现"实际很宽、标签写着 SELF"这种误导性诊断信息。
_SCOPE_LABEL_PRIORITY: tuple[DataScope, ...] = (
    DataScope.SELF,
    DataScope.DEPARTMENT,
    DataScope.CUSTOM,
    DataScope.DEPARTMENT_CHILDREN,
    DataScope.ALL,
)


def widest_data_scope(scopes: Sequence[DataScope]) -> DataScope:
    """在一组策略中取**最宽**的一个（按 `_SCOPE_LABEL_PRIORITY`）。

    用途：多角色合并后的"代表策略"标签（诊断 / 审计 / 前端展示）。
    真正的判权依据始终是 `ResolvedScope` 的
    `department_ids` / `restrict_to_actor` / `include_self` 三个字段，
    本函数只解决"合并后该怎么称呼"这一表达问题。

    为什么单独抽成函数：认证层（Phase 4）构造 `CurrentActor` 时也要填一个
    代表策略，若各处自行写 `max(...)`，一旦优先级表调整就会出现
    "同一组角色在不同路径得到不同标签"的漂移。

    Raises:
        ValueError: `scopes` 为空（无策略就无"最宽者"，不得凭空造出一个）。
    """
    if not scopes:
        raise ValueError("无法在空策略集合上取最宽者。")
    return max(scopes, key=_SCOPE_LABEL_PRIORITY.index)


@dataclass(frozen=True, slots=True)
class RoleScopeConfig:
    """**单个角色**的数据范围配置（DD-19 合并的输入单元）。

    为什么单独一个类型
    ----------------
    `CurrentActor.data_scope` 只能表达"这个用户的范围策略"，
    无法表达"该用户持有 3 个角色、各自的策略分别是什么"。
    而 DD-19 的求并规则恰恰需要逐角色输入，
    因此把"角色 → 范围配置"显式建模，避免调用方各自拼字典。

    Attributes:
        role_id: 角色 ID（诊断与审计用）。
        data_scope: 该角色配置的策略。
        custom_department_ids: 仅当 `data_scope == CUSTOM` 时有效，
            来自 DD-07 冻结的 `role_custom_scope_departments` 子表。
    """

    role_id: int
    data_scope: DataScope
    custom_department_ids: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        # 非 CUSTOM 却携带 CUSTOM 集合 = 典型的"以为已限定、实际未必"陷阱；
        # 与本项目 `RoleDataScopeService` 对外的拒绝口径保持一致（fail-closed）。
        if self.data_scope is not DataScope.CUSTOM and self.custom_department_ids:
            raise ValueError(
                f"非 CUSTOM 角色（role_id={self.role_id}）不得携带 custom_department_ids；"
                "这通常意味着读取残留行后没有清理。"
            )


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    """已解析的数据范围约束，供 Repository 下推到 SQL。

    Attributes:
        scope: 来源策略（多角色合并后为其中**最宽**的策略），
            仅用于诊断与审计。
        actor_id: 当前操作者用户 ID；`restrict_to_actor` / `include_self`
            为真时必须提供。
        department_ids: 允许访问的部门 ID 集合。
            **None 仅允许出现在 ALL**；空集合表示不可见任何部门。
        restrict_to_actor: 用户维度是否**只剩**本人（SELF）。
            为真时用户维度条件严格为 `id = actor_id`，不叠加部门条件。
        include_self: 用户维度是否在部门集合之外**额外**包含本人。
            来自"SELF ∪ 其他策略"的合并结果（DD-19）。
            只做加法，绝不放宽部门维度。
        source_scopes: 合并前的原始策略集合（诊断 / 前端 data scope 输出用）。
    """

    scope: DataScope
    actor_id: int | None = None
    department_ids: frozenset[int] | None = None
    restrict_to_actor: bool = False
    include_self: bool = False
    source_scopes: frozenset[DataScope] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.department_ids is None and self.scope is not DataScope.ALL:
            raise ValueError(
                f"fail-closed：scope={self.scope.value} 不允许 department_ids=None "
                "（只有 ALL 表示部门维度不限制）。请传入具体部门集合，空集合表示无可见部门。"
            )
        if self.restrict_to_actor and self.actor_id is None:
            raise ValueError("fail-closed：restrict_to_actor=True 时必须提供 actor_id。")
        if self.include_self and self.actor_id is None:
            raise ValueError("fail-closed：include_self=True 时必须提供 actor_id。")
        if self.scope is DataScope.SELF and not self.restrict_to_actor:
            raise ValueError("fail-closed：SELF 策略必须设置 restrict_to_actor=True。")

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------
    @classmethod
    def global_scope(cls, *, actor_id: int | None = None) -> ResolvedScope:
        """全局范围：部门维度与用户维度均不限制（仅 SUPER_ADMIN / ALL）。"""
        return cls(
            scope=DataScope.ALL,
            actor_id=actor_id,
            department_ids=None,
            source_scopes=frozenset({DataScope.ALL}),
        )

    @classmethod
    def for_departments(
        cls,
        department_ids: frozenset[int],
        *,
        scope: DataScope = DataScope.DEPARTMENT_CHILDREN,
        actor_id: int | None = None,
        include_self: bool = False,
    ) -> ResolvedScope:
        """限定到给定部门集合（空集合 = 什么都看不到）。"""
        if scope is DataScope.ALL:
            raise ValueError("ALL 不允许指定部门集合；请使用 global_scope()。")
        return cls(
            scope=scope,
            actor_id=actor_id,
            department_ids=department_ids,
            include_self=include_self,
            source_scopes=frozenset({scope}),
        )

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
            include_self=True,
            source_scopes=frozenset({DataScope.SELF}),
        )

    @classmethod
    def merge(cls, scopes: Sequence[ResolvedScope], *, actor_id: int | None) -> ResolvedScope:
        """按 DD-19 冻结规则合并多个角色的数据范围（**求并 / 最宽**）。

        规则：
        1. 任一角色为 ALL（`is_unrestricted_departments`）→ 结果为全局；
        2. 部门集合取并集；
        3. 仅当**全部**角色都是 SELF 时，结果才"仅本人"；
           否则只要有一个 SELF，就在部门集合之外**额外**包含本人。

        为什么"部分 SELF"不能简化为"忽略 SELF"：SELF 角色表达了
        "该角色只允许看自己"。忽略它会让只在 SELF 范围内的数据被
        部门集合覆盖掉 —— 那不是求并，而是求交的另一半。
        因此用 `include_self` 做加法，语义精确。

        Raises:
            ValueError: `scopes` 为空（无角色即无范围，调用方不得构造空合并）。
        """
        if not scopes:
            raise ValueError("fail-closed：无法合并空的数据范围集合（无角色即无范围）。")

        if any(item.is_unrestricted_departments for item in scopes):
            return cls.global_scope(actor_id=actor_id)

        departments: frozenset[int] = frozenset()
        for item in scopes:
            assert item.department_ids is not None  # 由不变量保证：非 ALL 必有集合
            departments |= item.department_ids

        all_self = all(item.restrict_to_actor for item in scopes)
        any_self = any(item.restrict_to_actor for item in scopes)
        label = widest_data_scope([item.scope for item in scopes])

        return cls(
            scope=label,
            actor_id=actor_id,
            department_ids=departments,
            restrict_to_actor=all_self,
            include_self=any_self,
            source_scopes=frozenset(item.scope for item in scopes),
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
        """是否为"空部门范围"：无任何可见部门。

        fail-closed 关键路径：必须翻译为 SQL `FALSE`，而非忽略条件。
        注意：`include_self=True` 时用户维度仍应放行本人 ——
        调用方必须用 `user_scope_condition`，而**不是**直接拿本属性当整体结论。
        """
        return self.department_ids is not None and len(self.department_ids) == 0

    @property
    def denies_all_users(self) -> bool:
        """用户维度是否什么都看不到（空部门 **且** 不包含本人）。"""
        return self.denies_all_departments and not self.include_self and not self.restrict_to_actor

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

    def allows_user(self, *, user_id: int, department_id: int | None) -> bool:
        """目标**用户**是否落在本范围内（服务端二次校验入口）。

        与 `scope_filters.user_scope_condition` 保持同一语义，
        避免"SQL 过滤一套、Python 校验另一套"的双份真相。

        语义顺序必须与 SQL 版本一致：
        1. `restrict_to_actor` → 只看本人；
        2. 部门维度不限制 → 全部通过；
        3. 部门在集合内 → 通过；
        4. `include_self` 且是本人 → 通过；
        5. 否则拒绝。
        """
        if self.restrict_to_actor:
            return self.actor_id is not None and user_id == self.actor_id
        if self.is_unrestricted_departments:
            return True
        if department_id is not None and self.allows_department(department_id):
            return True
        return self.include_self and self.actor_id is not None and user_id == self.actor_id


__all__ = ["DataScope", "ResolvedScope", "RoleScopeConfig", "widest_data_scope"]
