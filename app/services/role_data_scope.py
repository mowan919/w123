"""角色数据范围服务（Phase 3 / Task 3.10 —— DD-07 已冻结部分）。

Frozen / 已裁定依据
------------------
- Spec `03 §10`：数据范围支持 ALL / DEPARTMENT / DEPARTMENT_CHILDREN /
  SELF / CUSTOM；部门管理员默认 `DEPARTMENT_CHILDREN`。
- Spec `07 §5`：`role_permissions` 等关联表；数据范围是角色维度配置。
- Spec `08 §7`：`GET/PUT /roles/{id}/data-scope`（人类裁定沿用）。
- 人类裁定（Phase 3 冻结）：CUSTOM 采用 `roles.data_scope` 列 +
  `role_custom_scope_departments` 子表持久化。
- Spec `11 §5`：缓存安全取向 —— 宁可拒绝，也不放行过期权限。
- Spec `10 §3`：SUPER_ADMIN bypass 集中封装，禁止散落。

本模块补齐 DD-07 要求的六项
--------------------------
存储 / 查询 / 更新 / 删除 / 审计 —— 全部在授权层之后执行。
第六项"授权校验"**已不再是 INTERIM**：DD-20 冻结后由 API Permission 承担。

授权口径（Phase 3 变更）
----------------------
Phase 2 时判定是 INTERIM 保守默认（仅 SUPER_ADMIN），因为权限资源定义入口
缺失（CONFLICT-001）导致没有可依据的权限位。DD-20 冻结后
`AuthorizationService.assert_can_manage_roles` 改为基于
`ApiPermissionCode.ROLE_MANAGE` 判定，SUPER_ADMIN 走集中式 bypass
（Spec `10 §3`）。本服务内**不出现** `if actor.is_super_admin` 分支。

登记的待确认项
-------------
(A) `scope != CUSTOM` 时若请求体携带非空 `department_ids`，本服务**拒绝**
    （而非静默丢弃），避免"以为已经限定、实际未限定"的错觉；
(B) CUSTOM 部门集合当前只校验**存在且未删除**，**不**校验是否落在操作者的
    数据范围内 —— 该规则 Spec 未规定，不得自行外推；
(C) 多角色数据范围的**合并规则**已由 **DD-19 冻结为"可见集合求并（最宽）"**，
    但其实现在 `ResolvedScope.merge` 与 `EffectivePermissionService`，
    本服务仍**只做单角色读写**（保持职责单一）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditEvent, AuditRecorder, AuditResult, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, NotFoundError, PermissionDeniedError
from app.core.scope import DataScope
from app.models.role import Role
from app.repositories.department import DepartmentRepository
from app.repositories.permission import PermissionVersionRepository
from app.repositories.role import RoleRepository
from app.services.authorization import AuthorizationService

_RESOURCE_TYPE = "ROLE"


@dataclass(frozen=True, slots=True)
class RoleDataScope:
    """角色数据范围视图（领域对象，非 API 契约）。

    Attributes:
        role_id: 角色 ID。
        scope: 数据范围策略。
        department_ids: CUSTOM 的部门集合；非 CUSTOM 时恒为**空集合**
            （非 CUSTOM 角色不得在关联表留下残留行）。
    """

    role_id: int
    scope: DataScope
    department_ids: frozenset[int] = frozenset()

    @property
    def is_custom(self) -> bool:
        """是否为 CUSTOM 策略。"""
        return self.scope is DataScope.CUSTOM


def _snapshot(view: RoleDataScope) -> dict[str, Any]:
    """生成审计快照（只含范围配置，不含任何敏感字段）。"""
    return {
        "role_id": view.role_id,
        "data_scope": view.scope.value,
        "custom_department_ids": sorted(view.department_ids),
    }


class RoleDataScopeService:
    """角色数据范围的读写与审计。"""

    def __init__(self, session: AsyncSession, *, audit: AuditRecorder | None = None) -> None:
        self._session = session
        self._roles = RoleRepository(session)
        self._versions = PermissionVersionRepository(session)
        self._departments = DepartmentRepository(session)
        self._authz = AuthorizationService(session)
        self._audit = audit or NullAuditRecorder()

    # ------------------------------------------------------------------
    # 内部：审计
    # ------------------------------------------------------------------
    def _audit_success(
        self,
        *,
        actor: CurrentActor,
        action: AuditAction,
        resource_id: int,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        self._audit.record(
            AuditEvent.build(
                action=action,
                resource_type=_RESOURCE_TYPE,
                resource_id=resource_id,
                operator_id=actor.user_id,
                operator_username=actor.username,
                result=AuditResult.SUCCESS,
                before_data=before,
                after_data=after,
                ip=actor.ip,
                user_agent=actor.user_agent,
            )
        )

    def _audit_denied(
        self,
        *,
        actor: CurrentActor,
        action: AuditAction,
        resource_id: int | None,
        error_code: int,
    ) -> None:
        """权限拒绝必须留痕（Spec `10 §8` / `00 §7`）。"""
        self._audit.record(
            AuditEvent.build(
                action=action,
                resource_type=_RESOURCE_TYPE,
                resource_id=resource_id,
                operator_id=actor.user_id,
                operator_username=actor.username,
                result=AuditResult.FAILURE,
                error_code=error_code,
                ip=actor.ip,
                user_agent=actor.user_agent,
            )
        )

    @contextmanager
    def _denial_audited(
        self, *, actor: CurrentActor, action: AuditAction, resource_id: int | None
    ) -> Iterator[None]:
        """把授权拒绝统一写成 FAILURE 审计。

        为什么只捕获 `PermissionDeniedError`
        ---------------------------------
        `NotFoundError` 是"目标不存在"，不是越权；把它记成 FAILURE 会让
        审计里混入正常操作（例如并发删除后的重试），削弱 FAILURE 的信号价值。
        本模块**没有** `ConflictError` 语义（数据范围写入不产生业务冲突），
        故只捕获 `PermissionDeniedError`。
        """
        try:
            yield
        except PermissionDeniedError as exc:
            self._audit_denied(
                actor=actor, action=action, resource_id=resource_id, error_code=exc.code
            )
            raise

    # ------------------------------------------------------------------
    # 内部：校验
    # ------------------------------------------------------------------
    async def _load_role(self, *, actor: CurrentActor, role_id: int, action: AuditAction) -> Role:
        """**角色目标**的唯一入口：授权校验 + 读取。

        所有以角色为目标的写操作都必须经由此入口，
        不得各自实现授权判断（Spec `10 §3` 集中封装）。
        """
        with self._denial_audited(actor=actor, action=action, resource_id=role_id):
            await self._authz.assert_can_manage_roles(actor=actor)

        role = await self._roles.get(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        return role

    @staticmethod
    def _assert_scope_arguments(*, scope: DataScope, department_ids: frozenset[int]) -> None:
        """校验 scope 与 department_ids 的组合是否自洽。

        `scope != CUSTOM` 却给了部门集合，说明调用方对语义理解有误；
        静默丢弃会让调用方误以为"已限定到这些部门"，
        是典型的"以为安全实则更宽"的陷阱，因此直接拒绝。
        """
        if scope is not DataScope.CUSTOM and department_ids:
            raise BadRequestError("只有 CUSTOM 数据范围可以指定部门集合")

    async def _assert_departments_exist(self, department_ids: frozenset[int]) -> None:
        """校验 CUSTOM 引用的部门存在且未删除（引用完整性，非授权判断）。"""
        if not department_ids:
            return
        existing = await self._departments.existing_ids(department_ids)
        missing = department_ids - existing
        if missing:
            raise BadRequestError(f"CUSTOM 数据范围引用了不存在的部门：{sorted(missing)}")

    async def _current_view(self, role: Role) -> RoleDataScope:
        """读取角色当前的数据范围视图（非 CUSTOM 一律归一为空集合）。"""
        if role.data_scope is not DataScope.CUSTOM:
            return RoleDataScope(role_id=role.id, scope=role.data_scope)
        ids = await self._roles.list_custom_scope_department_ids(role.id)
        return RoleDataScope(role_id=role.id, scope=DataScope.CUSTOM, department_ids=ids)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def get(self, *, actor: CurrentActor, role_id: int) -> RoleDataScope:
        """查询角色数据范围（含授权校验与审计）。"""
        role = await self._load_role(
            actor=actor, role_id=role_id, action=AuditAction.ROLE_DATA_SCOPE_READ
        )
        view = await self._current_view(role)
        self._audit_success(
            actor=actor,
            action=AuditAction.ROLE_DATA_SCOPE_READ,
            resource_id=role_id,
            after=_snapshot(view),
        )
        return view

    # ------------------------------------------------------------------
    # 更新 / 删除
    # ------------------------------------------------------------------
    async def set_scope(
        self,
        *,
        actor: CurrentActor,
        role_id: int,
        scope: DataScope,
        department_ids: frozenset[int] = frozenset(),
    ) -> RoleDataScope:
        """设置角色数据范围。

        语义要点
        --------
        - 切到 CUSTOM：整体替换 CUSTOM 部门集合；
        - 从 CUSTOM 切走：**清空** `role_custom_scope_departments` 残留行。
          不清空将导致"改回 CUSTOM 时静默继承过期部门集合"的权限放大路径
          （Spec `11 §5`）。
        """
        role = await self._load_role(
            actor=actor, role_id=role_id, action=AuditAction.ROLE_DATA_SCOPE_UPDATE
        )
        self._assert_scope_arguments(scope=scope, department_ids=department_ids)

        before = await self._current_view(role)

        if scope is DataScope.CUSTOM:
            await self._assert_departments_exist(department_ids)
            role.data_scope = scope
            await self._roles.replace_custom_scope_departments(role_id, department_ids)
        else:
            role.data_scope = scope
            await self._roles.clear_custom_scope_departments(role_id)
        await self._session.flush()

        # 数据范围变化会直接改变该角色持有者的可见数据边界 → 递增权限版本
        # （Spec `11 §2`）。漏掉这一步会让"改了范围但缓存/前端仍按旧范围"
        # 违反 `00 §1#5` 的立即生效。
        await self._versions.bump()

        after = RoleDataScope(
            role_id=role_id,
            scope=scope,
            department_ids=department_ids if scope is DataScope.CUSTOM else frozenset(),
        )
        self._audit_success(
            actor=actor,
            action=AuditAction.ROLE_DATA_SCOPE_UPDATE,
            resource_id=role_id,
            before=_snapshot(before),
            after=_snapshot(after),
        )
        return after

    async def clear_custom_scope(self, *, actor: CurrentActor, role_id: int) -> RoleDataScope:
        """删除角色的 CUSTOM 部门集合，并把策略降级为 `SELF`（fail-closed）。

        降级方向的选择：清空集合后若仍标记 CUSTOM，该角色的有效范围就是
        **空集合**（什么都看不到），语义上等同于"配置损坏"。而 Spec `11 §5`
        要求宁可拒绝也不能放大 —— 因此降级到最小的合法策略 `SELF`，
        既不放权，也让配置保持自洽。

        注意：本操作**不**删除角色本身，只删除其 CUSTOM 范围配置。
        """
        role = await self._load_role(
            actor=actor, role_id=role_id, action=AuditAction.ROLE_DATA_SCOPE_UPDATE
        )
        before = await self._current_view(role)

        cleared = await self._roles.clear_custom_scope_departments(role_id)
        role.data_scope = DataScope.SELF
        await self._session.flush()
        await self._versions.bump()

        after = RoleDataScope(role_id=role_id, scope=DataScope.SELF)
        self._audit_success(
            actor=actor,
            action=AuditAction.ROLE_DATA_SCOPE_UPDATE,
            resource_id=role_id,
            before={**_snapshot(before), "cleared_department_ids": sorted(cleared)},
            after=_snapshot(after),
        )
        return after


__all__ = ["RoleDataScope", "RoleDataScopeService"]
