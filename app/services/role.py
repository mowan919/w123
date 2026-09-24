"""角色服务（Task 3.3：Role CRUD + 删除引用检查）。

Frozen / 已裁定依据
------------------
- Spec `03 §2`：Role 字段 id / role_code / role_name / status / description /
  created_at / updated_at / deleted_at。
- Spec `08 §7`：`GET|POST /roles`、`PUT /roles/{id}`、`POST /roles/{id}/delete`。
- Spec `03 §4`：必须避免"删除父角色导致隐式错误"。
- Spec `00 §6` / `07 §3`：默认逻辑删除；唯一约束考虑逻辑删除。
- Spec `11 §2`：权限修改必须递增 permission version 并使旧缓存失效。
- Spec `10 §3`：授权判断集中在 `AuthorizationService`，
  业务 Service 中不出现 `if actor.is_super_admin` 分支。
- **DD-20 已冻结**：管理角色需要 `ApiPermissionCode.ROLE_MANAGE`。

删除语义（本模块最重要的设计点）
----------------------------
角色被删除时，与之关联的数据分三类处理，**必须区分**：

1. **用户持有（`user_roles`）→ 拒绝删除（409）**。
   静默清除会让这些用户"莫名其妙失去角色"，是隐式权限变更。
2. **继承关系（`role_inheritances`）→ 拒绝删除（409）**。
   这正是 Spec `03 §4`"删除父角色导致隐式错误"要避免的情形：
   删掉父角色会让子角色静默掉权限。
3. **权限授权（`role_permissions` / `role_field_permissions`）
   与 CUSTOM 范围行（`role_custom_scope_departments`）→ 级联清理**。
   它们是**角色的从属数据**，不构成其他实体的依赖；
   清理不会改变其他任何实体的可见状态，且不清理会让这些行
   变成无主的"僵尸授权"，干扰资源删除的引用检查。

因此规则是"**他人的依赖 → 拒绝；自己的从属 → 清理**"，
拒绝优于静默级联（拒绝是显式的，级联是隐式的）。

`role_code` 不可通过 `PUT /roles/{id}` 修改
----------------------------------------
编码是角色的**稳定标识**：SUPER_ADMIN 判定、API 资源的引用、审计检索
都依赖它。允许改码会引入"把 SUPER_ADMIN 改名为其它码 → 系统静默失去
超级管理员入口"这类跨模块后果。因此 `update` 只接受
`role_name` / `description` / `status`；需要改码时应新建角色并迁移。
（该取舍登记在 `docs/DESIGN-DECISIONS.md` 的 INTERIM 表中。）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditRecorder, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.db.base import utc_now
from app.models.enums import RoleStatus
from app.models.role import Role
from app.repositories.permission import (
    PermissionVersionRepository,
    RoleInheritanceRepository,
    RolePermissionRepository,
)
from app.repositories.role import RoleRepository
from app.services.audit_guard import AuditGuard
from app.services.authorization import AuthorizationService

#: 审计资源类型。
RESOURCE_TYPE = "ROLE"

#: 角色编码 / 名称长度上限（与 `app.models.role` 的列定义一致）。
#:
#: Spec 未规定长度，此处取与列一致的值并在服务层预校验，
#: 目的是把"超长 → 数据库报错 → 500"变成"超长 → 400 且信息明确"。
MAX_ROLE_CODE_LENGTH = 64
MAX_ROLE_NAME_LENGTH = 128
MAX_DESCRIPTION_LENGTH = 255


@dataclass(frozen=True, slots=True)
class RolePage:
    """角色分页结果（领域对象；分页协议沿用人类已裁定的 `pageNum`/`pageSize`）。"""

    items: list[Role]
    total: int
    page_num: int
    page_size: int


def _snapshot(role: Role) -> dict[str, Any]:
    """角色审计快照（不含任何敏感字段）。"""
    return {
        "id": role.id,
        "role_code": role.role_code,
        "role_name": role.role_name,
        "status": role.status.value if role.status is not None else None,
        "description": role.description,
        "data_scope": role.data_scope.value if role.data_scope is not None else None,
        "deleted_at": role.deleted_at.isoformat() if role.deleted_at else None,
    }


class RoleService:
    """角色业务服务（CRUD + 引用检查 + 审计）。"""

    def __init__(self, session: AsyncSession, *, audit: AuditRecorder | None = None) -> None:
        self._session = session
        self._roles = RoleRepository(session)
        self._grants = RolePermissionRepository(session)
        self._inheritances = RoleInheritanceRepository(session)
        self._versions = PermissionVersionRepository(session)
        self._authz = AuthorizationService(session)
        self._guard = AuditGuard(audit or NullAuditRecorder(), RESOURCE_TYPE)

    # ------------------------------------------------------------------
    # 内部：目标加载与授权
    # ------------------------------------------------------------------
    async def _load_role(self, *, actor: CurrentActor, role_id: int, action: AuditAction) -> Role:
        """**角色目标**的唯一入口：授权校验 + 读取。

        所有以角色为目标的写操作都必须经由此入口（Spec `10 §3` 集中封装），
        不得各自实现授权判断 —— 散落写法必然漏掉某条路径的 FAILURE 审计。
        """
        with self._guard.denial_audited(actor=actor, action=action, resource_id=role_id):
            await self._authz.assert_can_manage_roles(actor=actor)

        role = await self._roles.get(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        return role

    @staticmethod
    def _assert_text_lengths(
        *,
        role_code: str | None = None,
        role_name: str | None = None,
        description: str | None = None,
    ) -> None:
        """字段长度与非空校验（把数据库错误提前为 400）。"""
        if role_code is not None:
            if not role_code.strip():
                raise BadRequestError("role_code 不能为空")
            if len(role_code) > MAX_ROLE_CODE_LENGTH:
                raise BadRequestError(f"role_code 长度不得超过 {MAX_ROLE_CODE_LENGTH}")
        if role_name is not None:
            if not role_name.strip():
                raise BadRequestError("role_name 不能为空")
            if len(role_name) > MAX_ROLE_NAME_LENGTH:
                raise BadRequestError(f"role_name 长度不得超过 {MAX_ROLE_NAME_LENGTH}")
        if description is not None and len(description) > MAX_DESCRIPTION_LENGTH:
            raise BadRequestError(f"description 长度不得超过 {MAX_DESCRIPTION_LENGTH}")

    async def _assert_role_deletable(self, role: Role) -> None:
        """删除前的引用检查（规则见模块说明）。

        两条拒绝都以 `ConflictError` 抛出，由外层拒绝守卫记 FAILURE 审计 ——
        它们代表"我们拒绝了某个请求"，属于审计关心的内容。
        """
        holders = await self._roles.count_users_for_roles([role.id])
        if holders:
            raise ConflictError(f"角色仍被 {holders} 个用户持有，请先解除用户关联后再删除")

        references = await self._inheritances.count_references(role.id)
        if references:
            raise ConflictError(
                "角色仍参与角色继承关系，请先解除继承后再删除（删除父角色会让子角色静默失去权限）"
            )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def get(self, *, actor: CurrentActor, role_id: int) -> Role:
        """按 ID 读取角色（授权拒绝留痕）。"""
        return await self._load_role(actor=actor, role_id=role_id, action=AuditAction.ROLE_READ)

    async def list_roles(
        self,
        *,
        actor: CurrentActor,
        keyword: str | None = None,
        status: RoleStatus | None = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> RolePage:
        """分页列出角色。

        读操作同样受 `ROLE_MANAGE` 约束：角色清单本身是敏感信息
        （暴露了系统的授权分层），不能对无权限者开放。
        """
        if page_num < 1:
            raise BadRequestError("pageNum 必须大于等于 1")
        if not 1 <= page_size <= 100:
            raise BadRequestError("pageSize 必须在 1..100 之间")

        with self._guard.denial_audited(
            actor=actor, action=AuditAction.ROLE_READ, resource_id=None
        ):
            await self._authz.assert_can_manage_roles(actor=actor)

        items = await self._roles.list_roles(
            keyword=keyword, status=status, page_num=page_num, page_size=page_size
        )
        total = await self._roles.count_roles(keyword=keyword, status=status)
        return RolePage(items=items, total=total, page_num=page_num, page_size=page_size)

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------
    async def create(
        self,
        *,
        actor: CurrentActor,
        role_code: str,
        role_name: str,
        description: str | None = None,
        status: RoleStatus = RoleStatus.ACTIVE,
    ) -> Role:
        """创建角色。

        数据范围不在创建时设置：它走 `GET/PUT /roles/{id}/data-scope`
        （`08 §7`），从而保证 ROLE_DATA_SCOPE_UPDATE 审计不可被绕过。
        新角色使用列的默认值 `DEPARTMENT_CHILDREN`（部门管理员默认，
        `03 §10` 冻结），这是最保守的可用默认。
        """
        self._assert_text_lengths(role_code=role_code, role_name=role_name, description=description)

        with self._guard.denial_audited(
            actor=actor, action=AuditAction.ROLE_CREATE, resource_id=None
        ):
            await self._authz.assert_can_manage_roles(actor=actor)

        if await self._roles.get_by_code(role_code) is not None:
            raise ConflictError(f"角色编码已存在：{role_code}")

        role = Role(
            role_code=role_code,
            role_name=role_name,
            description=description,
            status=status,
        )
        await self._roles.add(role)

        # 新增角色本身不改变任何人已持有的权限（尚无用户持有、无授权），
        # 因此不递增权限版本 —— 避免无意义的版本抖动让缓存反复失效。
        self._guard.success(
            actor=actor,
            action=AuditAction.ROLE_CREATE,
            resource_id=role.id,
            after=_snapshot(role),
        )
        return role

    # ------------------------------------------------------------------
    # 修改
    # ------------------------------------------------------------------
    async def update(
        self,
        *,
        actor: CurrentActor,
        role_id: int,
        role_name: str | None = None,
        description: str | None = None,
        status: RoleStatus | None = None,
    ) -> Role:
        """修改角色名称 / 描述 / 状态。

        `role_code` 与 `data_scope` **不在此处**修改，理由见模块说明。
        """
        role = await self._load_role(actor=actor, role_id=role_id, action=AuditAction.ROLE_UPDATE)
        self._assert_text_lengths(role_name=role_name, description=description)

        before = _snapshot(role)
        status_changed = status is not None and status is not role.status

        if role_name is not None:
            role.role_name = role_name
        if description is not None:
            role.description = description
        if status is not None:
            role.status = status
        await self._session.flush()

        if status_changed:
            # 禁用 / 启用角色会直接改变该角色所有持有者的有效权限
            # （有效权限并集只认 ACTIVE 角色）→ 必须递增版本（Spec `11 §2`）。
            await self._versions.bump()

        self._guard.success(
            actor=actor,
            action=AuditAction.ROLE_UPDATE,
            resource_id=role.id,
            before=before,
            after=_snapshot(role),
        )
        return role

    # ------------------------------------------------------------------
    # 逻辑删除
    # ------------------------------------------------------------------
    async def delete(self, *, actor: CurrentActor, role_id: int) -> Role:
        """逻辑删除角色（引用拒绝 + 从属数据清理）。

        绝不物理删除（AGENTS.md §7 / Spec `00 §6`）。
        """
        role = await self._load_role(actor=actor, role_id=role_id, action=AuditAction.ROLE_DELETE)

        with self._guard.denial_audited(
            actor=actor, action=AuditAction.ROLE_DELETE, resource_id=role.id
        ):
            await self._assert_role_deletable(role)

        before = _snapshot(role)

        # 从属数据清理：只清"角色自己的"授权与范围配置。
        # 此时已确认无用户持有、无继承关系，因此不会影响任何其他实体的权限。
        removed_resource_ids, removed_field_levels = await self._grants.delete_all_for_role(role.id)
        await self._roles.clear_custom_scope_for_roles([role.id])

        role.status = RoleStatus.DISABLED
        role.deleted_at = utc_now()
        await self._session.flush()

        await self._versions.bump()

        self._guard.success(
            actor=actor,
            action=AuditAction.ROLE_DELETE,
            resource_id=role.id,
            before=before,
            after={
                **_snapshot(role),
                "cleared_resource_ids": sorted(removed_resource_ids),
                "cleared_field_ids": sorted(removed_field_levels),
            },
        )
        return role


__all__ = ["RESOURCE_TYPE", "RolePage", "RoleService"]
