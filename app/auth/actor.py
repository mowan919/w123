"""当前操作者（CurrentActor）。

Frozen 依据
-----------
- Spec `10 §2` Authorization：Authentication → Role → Permission → API Permission
  → Data Scope → Resource ownership / scope。
- Spec `10 §3`：SUPER_ADMIN 相关 bypass **必须集中封装**，
  不能让普通管理员通过修改请求参数 / user_id / session_id / 直接调用 API 绕过保护。
- Spec `00 §1#7` / `15 D-007`：SUPER_ADMIN 仅本人可 logout，其他管理员不能踢。

设计说明
-------
`CurrentActor` 是**认证结果的载体**，只承载"我是谁、我的范围策略是什么"，
不承载任何授权判断逻辑。判断入口集中在
`app/services/data_scope.py` 与各 Service 的服务端二次校验。

`is_super_admin` 由 `SUPER_ADMIN_ROLE_CODE` **统一推导**，
业务代码不得自行 `if user.username == 'admin'` 之类的判断。

Phase 2 边界
-----------
认证在后续 Phase 实现（`PHASE-004-AUTH`），本 Phase **不暴露 HTTP 端点**，
因此没有"从 Token 解析 Actor"的代码。当前 Actor 由测试或上游显式构造。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.scope import DataScope

#: SUPER_ADMIN 的角色编码。
#:
#: INTERIM：Spec 未冻结 SUPER_ADMIN 的标识方式（角色编码字面量未定义）。
#: 此处集中定义单点常量，避免散落字符串；DD 冻结后只需改这一处。
SUPER_ADMIN_ROLE_CODE = "SUPER_ADMIN"


@dataclass(frozen=True, slots=True)
class CurrentActor:
    """已认证的当前操作者。

    Attributes:
        user_id: 操作者用户 ID。
        username: 操作者登录名（审计用；日志中需按规则脱敏，用户名本身不属敏感项）。
        role_codes: 持有角色编码集合（多角色）。
        data_scope: 由角色配置解析出的数据范围策略。
        department_id: 所属部门 ID；部门范围计算的基础。None 表示未分配部门。
        custom_department_ids: CUSTOM 范围的部门集合。
            `16 §34#7`（DD-07）未冻结其**存储**，因此此处只接受外部传入。
            None 表示"未配置" → 解析时按空集合处理（fail-closed）。
        ip / user_agent: 审计字段（Spec 06 §2）。
    """

    user_id: int
    username: str
    role_codes: frozenset[str] = field(default_factory=frozenset)
    data_scope: DataScope = DataScope.SELF
    department_id: int | None = None
    custom_department_ids: frozenset[int] | None = None
    ip: str | None = None
    user_agent: str | None = None

    @property
    def is_super_admin(self) -> bool:
        """是否为 SUPER_ADMIN（统一推导入口）。"""
        return SUPER_ADMIN_ROLE_CODE in self.role_codes

    def has_role(self, role_code: str) -> bool:
        """是否持有指定角色。"""
        return role_code in self.role_codes

    @classmethod
    def super_admin(
        cls,
        *,
        user_id: int,
        username: str,
        department_id: int | None = None,
    ) -> CurrentActor:
        """构造 SUPER_ADMIN 操作者（用于测试与 Seed）。"""
        return cls(
            user_id=user_id,
            username=username,
            role_codes=frozenset({SUPER_ADMIN_ROLE_CODE}),
            data_scope=DataScope.ALL,
            department_id=department_id,
        )


__all__ = ["SUPER_ADMIN_ROLE_CODE", "CurrentActor"]
