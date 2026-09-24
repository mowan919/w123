"""部门服务。

Frozen / 已裁定依据
------------------
- Spec `02 §1`：树形组织、创建、修改、禁用、逻辑删除、查询子部门、范围计算。
- Spec `02 §6`：不得操作范围外部门。
- Spec `08 §6`：`GET /departments/tree`、`POST /departments`、
  `PUT /departments/{id}`、`POST /departments/{id}/disable`
  （人类裁定补齐 `POST /departments/{id}/delete`）。
- Spec `10 §3`：服务端必须重新校验，不能让调用方通过改参数绕过范围。
- 人类裁定：部门逻辑删除时，若仍有未删除子部门或在册用户 → **拒绝删除**。

关键安全行为
-----------
1. `department_id` / `parent_id` **一律服务端校验范围**，不信任请求体；
2. 非全局范围的操作者**不能创建根部门**（根节点必然落在其子树之外）；
3. `update` **不接受 status 变更**，禁用必须走 `disable()`，
   以保证 DEPARTMENT_DISABLE 审计不可被绕过；
4. 移动部门时校验**环**（新父节点不得是自己或自己的后代）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditEvent, AuditRecorder, AuditResult, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.scope import ResolvedScope
from app.db.base import utc_now
from app.models.department import Department
from app.models.enums import DepartmentStatus
from app.repositories.department import DepartmentRepository
from app.services.data_scope import DataScopeResolver


class _Unset:
    """哨兵类型：区分"未提供该字段"与"显式置为 None"。"""

    __slots__ = ()


_UNSET: Final = _Unset()


@dataclass
class DepartmentTreeNode:
    """部门树节点（领域对象，非 API 契约）。"""

    id: int
    parent_id: int | None
    department_code: str
    department_name: str
    status: DepartmentStatus
    children: list[DepartmentTreeNode] = field(default_factory=list)


def _snapshot(department: Department) -> dict[str, Any]:
    """生成审计用快照（不含任何敏感字段）。"""
    return {
        "id": department.id,
        "parent_id": department.parent_id,
        "department_code": department.department_code,
        "department_name": department.department_name,
        "status": department.status.value if department.status is not None else None,
        "deleted_at": department.deleted_at.isoformat() if department.deleted_at else None,
    }


class DepartmentService:
    """部门业务服务。"""

    def __init__(self, session: AsyncSession, *, audit: AuditRecorder | None = None) -> None:
        self._session = session
        self._departments = DepartmentRepository(session)
        self._scope = DataScopeResolver(self._departments)
        self._audit = audit or NullAuditRecorder()

    # ------------------------------------------------------------------
    # 内部：审计
    # ------------------------------------------------------------------
    def _audit_success(
        self,
        *,
        actor: CurrentActor,
        action: AuditAction,
        resource_id: int | None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        self._audit.record(
            AuditEvent.build(
                action=action,
                resource_type="DEPARTMENT",
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
        """越权尝试必须留痕（Spec 10 §8：关键安全操作必须可审计）。"""
        self._audit.record(
            AuditEvent.build(
                action=action,
                resource_type="DEPARTMENT",
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
        """把**数据范围越权拒绝**统一写成 FAILURE 审计（FIX-002）。

        为什么只捕获 `PermissionDeniedError`
        ---------------------------------
        `ConflictError` 在本服务里表达的是**数据完整性拒绝**
        （部门编码重复、仍有子部门、仍有在册用户），
        属于业务规则冲突而非越权，按既有裁定不留 FAILURE 痕迹
        （见 `test_refused_delete_never_records_success`）。
        用户服务中的"最后一个 SUPER_ADMIN"是 `00 §1#7` 的
        **安全不变量**，语义不同，因此在 `UserService` 里连同
        `ConflictError` 一起捕获。

        为什么必须是上下文管理器
        ----------------------
        原先每处 `if not scope.allows_department(...): _audit_denied(...); raise`
        是**散落式**写法，漏写一处就产生"可越权且不留痕"的盲区
        （`_assert_parent_change_allowed` 的"移到根层级"分支即为一例）。
        统一守卫后，只要校验包在 `with` 内就不可能漏审计。
        """
        try:
            yield
        except PermissionDeniedError as exc:
            self._audit_denied(
                actor=actor,
                action=action,
                resource_id=resource_id,
                error_code=exc.code,
            )
            raise

    async def _load_target(
        self, *, actor: CurrentActor, department_id: int, action: AuditAction
    ) -> tuple[Department, ResolvedScope]:
        """**部门目标**的唯一入口：范围校验 + 读取。

        所有以"某个已存在部门"为目标的写操作都必须经由此入口，
        不得各自实现范围判断。
        """
        scope = await self._scope.resolve(actor)
        with self._denial_audited(actor=actor, action=action, resource_id=department_id):
            if not scope.allows_department(department_id):
                raise PermissionDeniedError("部门不在当前数据范围内")

        department = await self._departments.get(department_id)
        if department is None:
            raise NotFoundError("部门不存在")
        return department, scope

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def list_tree(self, *, actor: CurrentActor) -> list[DepartmentTreeNode]:
        """返回操作者数据范围内的部门树。

        范围在 SQL 中生效；范围内的"孤儿"节点（父节点在范围外）
        按根节点呈现，避免前端丢失子树。
        """
        scope = await self._scope.resolve(actor)
        rows = await self._departments.list_in_scope(scope)
        return self._build_tree(rows)

    @staticmethod
    def _build_tree(rows: list[Department]) -> list[DepartmentTreeNode]:
        """由已授权的行集合构建树（纯内存结构组装，不涉及授权过滤）。"""
        nodes: dict[int, DepartmentTreeNode] = {
            row.id: DepartmentTreeNode(
                id=row.id,
                parent_id=row.parent_id,
                department_code=row.department_code,
                department_name=row.department_name,
                status=row.status,
            )
            for row in rows
        }
        roots: list[DepartmentTreeNode] = []
        for node in nodes.values():
            parent = nodes.get(node.parent_id) if node.parent_id is not None else None
            if parent is None:
                roots.append(node)
            else:
                parent.children.append(node)
        roots.sort(key=lambda n: n.id)
        return roots

    async def get(self, *, actor: CurrentActor, department_id: int) -> Department:
        """按 ID 读取部门，并做范围校验（拒绝留痕）。"""
        department, _ = await self._load_target(
            actor=actor, department_id=department_id, action=AuditAction.DEPARTMENT_READ
        )
        return department

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    async def create(
        self,
        *,
        actor: CurrentActor,
        department_code: str,
        department_name: str,
        parent_id: int | None = None,
    ) -> Department:
        """创建部门。"""
        scope = await self._scope.resolve(actor)

        with self._denial_audited(
            actor=actor, action=AuditAction.DEPARTMENT_CREATE, resource_id=parent_id
        ):
            if parent_id is None:
                if not scope.is_unrestricted_departments:
                    raise PermissionDeniedError("非全局数据范围不允许创建根部门")
            elif not scope.allows_department(parent_id):
                raise PermissionDeniedError("父部门不在当前数据范围内")

        if parent_id is not None and await self._departments.get(parent_id) is None:
            raise NotFoundError("父部门不存在")

        await self._assert_code_available(department_code)

        department = Department(
            parent_id=parent_id,
            department_code=department_code,
            department_name=department_name,
            status=DepartmentStatus.ACTIVE,
        )
        await self._departments.add(department)
        self._audit_success(
            actor=actor,
            action=AuditAction.DEPARTMENT_CREATE,
            resource_id=department.id,
            after=_snapshot(department),
        )
        return department

    async def update(
        self,
        *,
        actor: CurrentActor,
        department_id: int,
        department_code: str | None = None,
        department_name: str | None = None,
        parent_id: int | _Unset | None = _UNSET,
    ) -> Department:
        """修改部门。

        `status` 不在此处修改：禁用必须走 `disable()`，
        以免绕过 DEPARTMENT_DISABLE 审计。
        """
        department, scope = await self._load_target(
            actor=actor, department_id=department_id, action=AuditAction.DEPARTMENT_UPDATE
        )

        before = _snapshot(department)

        if department_code is not None and department_code != department.department_code:
            await self._assert_code_available(department_code)
            department.department_code = department_code

        if department_name is not None:
            department.department_name = department_name

        if not isinstance(parent_id, _Unset):
            # 父节点变更同样统一经守卫留痕（含"移到根层级"这一分支）
            with self._denial_audited(
                actor=actor, action=AuditAction.DEPARTMENT_UPDATE, resource_id=department.id
            ):
                await self._assert_parent_change_allowed(
                    scope=scope, department=department, new_parent_id=parent_id
                )
            department.parent_id = parent_id

        await self._session.flush()
        self._audit_success(
            actor=actor,
            action=AuditAction.DEPARTMENT_UPDATE,
            resource_id=department.id,
            before=before,
            after=_snapshot(department),
        )
        return department

    async def disable(self, *, actor: CurrentActor, department_id: int) -> Department:
        """禁用部门。"""
        department, _ = await self._load_target(
            actor=actor, department_id=department_id, action=AuditAction.DEPARTMENT_DISABLE
        )

        before = _snapshot(department)
        department.status = DepartmentStatus.DISABLED
        await self._session.flush()
        self._audit_success(
            actor=actor,
            action=AuditAction.DEPARTMENT_DISABLE,
            resource_id=department.id,
            before=before,
            after=_snapshot(department),
        )
        return department

    async def delete(self, *, actor: CurrentActor, department_id: int) -> Department:
        """逻辑删除部门（服务端拒绝产生孤儿数据）。

        人类裁定：存在未删除的子部门，或该部门（含子部门）下仍有在册用户时，
        拒绝删除并返回 conflict。
        """
        department, _ = await self._load_target(
            actor=actor, department_id=department_id, action=AuditAction.DEPARTMENT_DELETE
        )

        children = await self._departments.count_children(department_id)
        if children > 0:
            raise ConflictError(f"该部门下仍有 {children} 个未删除的子部门，无法删除")

        if await self._departments.exists_user_in_subtree(department_id):
            raise ConflictError("该部门或其子部门下仍有在册用户，无法删除")

        before = _snapshot(department)
        department.deleted_at = utc_now()
        await self._session.flush()
        self._audit_success(
            actor=actor,
            action=AuditAction.DEPARTMENT_DELETE,
            resource_id=department.id,
            before=before,
            after=_snapshot(department),
        )
        return department

    # ------------------------------------------------------------------
    # 内部校验
    # ------------------------------------------------------------------
    async def _assert_code_available(self, department_code: str) -> None:
        """编码唯一性预校验（软删除感知）。"""
        existing = await self._departments.get_by_code(department_code)
        if existing is not None:
            raise ConflictError(f"部门编码已存在：{department_code}")

    async def _assert_parent_change_allowed(
        self,
        *,
        scope: ResolvedScope,
        department: Department,
        new_parent_id: int | None,
    ) -> None:
        """校验父节点变更是否合法（范围 + 环）。

        越权拒绝由调用处的 `_denial_audited` 统一留痕，本方法只负责判定，
        不再自行写审计 —— 避免"判定与留痕分散在两处"再次产生盲区。
        """
        if new_parent_id is None:
            if not scope.is_unrestricted_departments:
                raise PermissionDeniedError("非全局数据范围不允许把部门移动到根层级")
            return

        if new_parent_id == department.id:
            raise BadRequestError("父部门不能是自身")

        if not scope.allows_department(new_parent_id):
            raise PermissionDeniedError("目标父部门不在当前数据范围内")

        parent = await self._departments.get(new_parent_id)
        if parent is None:
            raise NotFoundError("目标父部门不存在")

        subtree = await self._departments.descendant_ids(department.id, include_self=True)
        if new_parent_id in subtree:
            raise ConflictError("不能把部门移动到自己的子部门下（会形成循环层级）")


__all__ = ["DepartmentService", "DepartmentTreeNode"]
