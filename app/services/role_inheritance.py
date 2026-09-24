"""角色继承服务（Task 3.5：继承关系的建立 / 解除 / 环路防护）。

Frozen / 已裁定依据
------------------
- Spec `00 §1#3` / `15 D-003` / `03 §4`：**V1 支持角色继承**；
  继承权限必须参与 Effective Permission 计算。
- Spec `03 §4` 必须避免四件事：循环继承 / 无限递归 / 重复权限 /
  删除父角色导致隐式错误。
- Spec `11 §2` / `§3`：权限修改立即生效并递增版本；角色继承属并发保护重点。
- **DD-05 已冻结（方案 A）**：邻接表 `role_inheritances(parent_role_id, child_role_id)`
  + 写入期环检测 + 递归 CTE(`UNION`) 展开 + 深度上限 32 + 删除被引用角色时拒绝。

三重环路防护（`03 §4`"循环继承"与"无限递归"）
----------------------------------------
1. **数据库**：`ck_role_inheritances_no_self_inheritance` 阻止自环（A→A）；
2. **写入期（本服务）**：建立 `parent ← child` 之前，展开 `parent` 的**祖先集合**，
   若其中包含 `child`，则新边会构成环 → 拒绝（409）。
   这是唯一能在"入库前"拦住环的地方。
3. **读取期（仓储）**：展开使用递归 CTE 的 `UNION`（去重）→ 即使库中已有环
   （例如人为绕过 API 直接写库），查询也**必然收敛**，不会无限递归。
   同时展开带**深度上限**，把异常长链暴露为错误而不是静默接受可疑结果。

第 2 步与第 3 步是互补而非冗余：第 2 步保证不会产生环，
第 3 步保证"已经产生的环不会把系统拖垮"。

方向说明（极易写反）
-----------------
`parent_role_id` 是**权限提供方**，`child_role_id` 是**权限获得方**：

```text
child ──继承──▶ parent      即 child 拥有 parent 的全部权限
```

因此"是否成环"的判定是：**`parent` 是否（间接）继承了 `child`**，
即 `child ∈ ancestors(parent)`。反过来判会放过真正的环。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditRecorder, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.models.role import Role
from app.repositories.permission import (
    PermissionVersionRepository,
    RoleInheritanceDepthExceededError,
    RoleInheritanceRepository,
)
from app.repositories.role import RoleRepository
from app.services.audit_guard import AuditGuard
from app.services.authorization import AuthorizationService
from app.services.effective_permission import MAX_ROLE_INHERITANCE_DEPTH

#: 审计资源类型（继承动作挂在**子角色**上：它才是权限变化的主体）。
RESOURCE_TYPE = "ROLE"


@dataclass(frozen=True, slots=True)
class InheritanceChain:
    """角色继承链视图（`03 §11` 权限预览的一部分）。"""

    role_id: int
    parent_role_ids: frozenset[int]
    child_role_ids: frozenset[int]
    ancestor_role_ids: frozenset[int]

    @property
    def direct_parents(self) -> frozenset[int]:
        """直接父角色。"""
        return self.parent_role_ids

    @property
    def direct_children(self) -> frozenset[int]:
        """直接子角色。"""
        return self.child_role_ids


class RoleInheritanceService:
    """角色继承关系的读写与环路防护。"""

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: AuditRecorder | None = None,
        max_depth: int = MAX_ROLE_INHERITANCE_DEPTH,
    ) -> None:
        self._session = session
        self._roles = RoleRepository(session)
        self._inheritances = RoleInheritanceRepository(session)
        self._versions = PermissionVersionRepository(session)
        self._authz = AuthorizationService(session)
        self._guard = AuditGuard(audit or NullAuditRecorder(), RESOURCE_TYPE)
        self._max_depth = max_depth

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    async def _assert_authorized(
        self, *, actor: CurrentActor, action: AuditAction, role_id: int | None
    ) -> None:
        with self._guard.denial_audited(actor=actor, action=action, resource_id=role_id):
            await self._authz.assert_can_manage_roles(actor=actor)

    async def _load_role(self, role_id: int, *, field: str) -> Role:
        """读取角色（未删除），用于校验继承关系两端都真实存在。"""
        role = await self._roles.get(role_id)
        if role is None:
            raise BadRequestError(f"{field} 指定的角色不存在或已删除：{role_id}")
        return role

    async def _assert_no_cycle(self, *, parent_role_id: int, child_role_id: int) -> None:
        """写入期环检测（见模块说明的方向）。

        需要检查两种情况：
        1. 新边本身是自环（`parent == child`）→ 数据库 CHECK 也会拦，但这里给出 400；
        2. 新边闭合出一个环：`child` 已经在 `parent` 的祖先集合里
           （等价于 parent 已经间接继承 child）。
        """
        if parent_role_id == child_role_id:
            raise BadRequestError("不能创建自继承关系")

        try:
            ancestors_of_parent = await self._inheritances.ancestor_ids(
                [parent_role_id], max_depth=self._max_depth
            )
        except RoleInheritanceDepthExceededError as exc:
            # 现有数据已经异常（很可能存在环）→ 拒绝继续写入并让运维介入。
            raise ConflictError(
                f"现有角色继承链异常（深度超过 {self._max_depth}），请先修复数据：{exc}"
            ) from exc

        if child_role_id in ancestors_of_parent:
            raise ConflictError("该继承关系会构成循环继承（被继承的角色已经间接继承了该角色）")

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def list_chain(self, *, actor: CurrentActor, role_id: int) -> InheritanceChain:
        """读取角色的直接继承关系与完整祖先集合。"""
        await self._assert_authorized(actor=actor, action=AuditAction.ROLE_READ, role_id=role_id)
        role = await self._roles.get(role_id)
        if role is None:
            raise NotFoundError("角色不存在")

        try:
            ancestors = await self._inheritances.ancestor_ids([role.id], max_depth=self._max_depth)
        except RoleInheritanceDepthExceededError as exc:
            raise ConflictError(str(exc)) from exc

        return InheritanceChain(
            role_id=role.id,
            parent_role_ids=await self._inheritances.direct_parent_ids(role.id),
            child_role_ids=await self._inheritances.direct_child_ids(role.id),
            ancestor_role_ids=ancestors,
        )

    # ------------------------------------------------------------------
    # 授予 / 解除
    # ------------------------------------------------------------------
    async def grant(
        self, *, actor: CurrentActor, parent_role_id: int, child_role_id: int
    ) -> InheritanceChain:
        """建立"`child` 继承 `parent`"的关系。

        成功后 `child` 的持有者立即获得 `parent` 的权限（Spec `00 §1#5`），
        因此必须递增权限版本（Spec `11 §2`）。
        """
        await self._assert_authorized(
            actor=actor, action=AuditAction.ROLE_INHERITANCE_GRANT, role_id=child_role_id
        )
        await self._load_role(parent_role_id, field="parent_role_id")
        await self._load_role(child_role_id, field="child_role_id")

        existing = await self._inheritances.get(
            parent_role_id=parent_role_id, child_role_id=child_role_id
        )

        with self._guard.denial_audited(
            actor=actor, action=AuditAction.ROLE_INHERITANCE_GRANT, resource_id=child_role_id
        ):
            await self._assert_no_cycle(parent_role_id=parent_role_id, child_role_id=child_role_id)

        if existing is None:
            await self._inheritances.add(parent_role_id=parent_role_id, child_role_id=child_role_id)
            await self._versions.bump()
            before: dict[str, Any] | None = None
        else:
            # 幂等：重复授予同一关系不产生副作用，也不抖动权限版本。
            before = {"already_existed": True}

        after = {
            "parent_role_id": parent_role_id,
            "child_role_id": child_role_id,
        }
        self._guard.success(
            actor=actor,
            action=AuditAction.ROLE_INHERITANCE_GRANT,
            resource_id=child_role_id,
            before=before,
            after=after,
        )
        return await self.list_chain(actor=actor, role_id=child_role_id)

    async def revoke(
        self, *, actor: CurrentActor, parent_role_id: int, child_role_id: int
    ) -> InheritanceChain:
        """解除继承关系。解除后 `child` 立即失去继承来的权限。"""
        await self._assert_authorized(
            actor=actor, action=AuditAction.ROLE_INHERITANCE_REVOKE, role_id=child_role_id
        )
        await self._load_role(parent_role_id, field="parent_role_id")
        await self._load_role(child_role_id, field="child_role_id")

        removed = await self._inheritances.remove(
            parent_role_id=parent_role_id, child_role_id=child_role_id
        )
        if removed:
            await self._versions.bump()
        else:
            raise NotFoundError("继承关系不存在")

        self._guard.success(
            actor=actor,
            action=AuditAction.ROLE_INHERITANCE_REVOKE,
            resource_id=child_role_id,
            before={"parent_role_id": parent_role_id, "child_role_id": child_role_id},
        )
        return await self.list_chain(actor=actor, role_id=child_role_id)

    # ------------------------------------------------------------------
    # 展开（供权限引擎与预览复用）
    # ------------------------------------------------------------------
    async def expand_role_ids(self, role_ids: frozenset[int]) -> frozenset[int]:
        """展开为"自身 ∪ 全部祖先"，不做授权校验。

        为什么不做授权校验：本方法是**权限计算的内部分步**，
        调用方（`EffectivePermissionService`）已经在权限判定的上下文里，
        追加一次授权查询既不必要也会把"计算"与"判定"耦合在一起。
        对外暴露的读写入口（`list_chain` / `grant` / `revoke`）**都**有授权校验。
        """
        if not role_ids:
            return frozenset()
        return await self._inheritances.expand_role_ids(sorted(role_ids), max_depth=self._max_depth)


__all__ = ["RESOURCE_TYPE", "InheritanceChain", "RoleInheritanceService"]
