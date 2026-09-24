"""角色权限授予服务（Task 3.6~3.9：pages / menus / buttons / apis / fields）。

Frozen / 已裁定依据
------------------
- Spec `08 §7`：`GET /roles/{id}/permissions`；
  `PUT /roles/{id}/permissions/{pages,menus,buttons,apis,fields}`。
- Spec `00 §1#2` / `15 D-002`：多角色权限取并集。
- Spec `00 §3` / `03 §9`：字段权限四级取值，由后端统一计算后输出。
- Spec `11 §2`：权限修改必须递增 permission version。
- **DD-20 已冻结**：请求体为**整体替换**语义 `{"resourceIds": [...]}`；
  `resource_code` 按类型逻辑删除感知唯一。
- **DD-06 已冻结**：字段授权携带 `accessLevel`，多角色合并取**最宽松者胜**。

整体替换而不是增量 add/remove
--------------------------
Spec 与 DD-20 均选择整体替换（PUT 语义），原因：

1. **幂等**：重复提交同一请求结果一致，重试安全（Spec `11 §4` 的取向）；
2. **可审计**：before/after 天然完整，能回答"这次改动到底让谁多了什么权限"；
   增量语义下审计只能看到"加了一条"，需要回放历史才能还原最终状态；
3. **与既有实现一致**：`replace_user_roles` / `replace_custom_scope_departments`
   都是整体替换，保持同一心智模型。

⚠️ 最容易写错的地方：替换必须**限定在单一资源类型内**
（由 `RolePermissionRepository.replace_resource_ids` 保证）。
如果实现成"先清空该角色全部授权再写入"，那么一次
`PUT /roles/{id}/permissions/pages` 会静默清掉该角色的 API 与 BUTTON 授权 ——
那是产品事故级的行为（权限静默缩小/错乱）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditRecorder, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, NotFoundError
from app.models.enums import FieldAccessLevel, PermissionResourceType
from app.models.permission import PermissionResource
from app.repositories.permission import (
    PermissionResourceRepository,
    PermissionVersionRepository,
    RolePermissionRepository,
)
from app.repositories.role import RoleRepository
from app.services.audit_guard import AuditGuard
from app.services.authorization import AuthorizationService

#: 审计资源类型（授权动作的审计挂在**角色**上，便于"某角色改了什么"检索）。
RESOURCE_TYPE = "ROLE"

#: 支持"整体替换"的资源类型（DD-20 冻结：四类二元权限）。
_BINARY_TYPES: dict[str, PermissionResourceType] = {
    "pages": PermissionResourceType.PAGE,
    "menus": PermissionResourceType.MENU,
    "buttons": PermissionResourceType.BUTTON,
    "apis": PermissionResourceType.API,
}


@dataclass(frozen=True, slots=True)
class RolePermissionView:
    """角色授权视图（`GET /roles/{id}/permissions` 的领域对象）。"""

    role_id: int
    page_ids: frozenset[int]
    menu_ids: frozenset[int]
    button_ids: frozenset[int]
    api_ids: frozenset[int]
    field_levels: dict[int, FieldAccessLevel]

    def ids_of(self, resource_type: PermissionResourceType) -> frozenset[int]:
        """按类型取授权资源 ID 集合。"""
        match resource_type:
            case PermissionResourceType.PAGE:
                return self.page_ids
            case PermissionResourceType.MENU:
                return self.menu_ids
            case PermissionResourceType.BUTTON:
                return self.button_ids
            case PermissionResourceType.API:
                return self.api_ids
            case PermissionResourceType.FIELD:
                return frozenset(self.field_levels)
        raise BadRequestError(f"未知资源类型：{resource_type!r}")


def _snapshot_view(view: RolePermissionView) -> dict[str, Any]:
    """授权视图的审计快照。"""
    return {
        "role_id": view.role_id,
        "page_ids": sorted(view.page_ids),
        "menu_ids": sorted(view.menu_ids),
        "button_ids": sorted(view.button_ids),
        "api_ids": sorted(view.api_ids),
        "field_levels": {str(key): value.value for key, value in sorted(view.field_levels.items())},
    }


class RolePermissionService:
    """角色权限授予的读写与审计。"""

    def __init__(self, session: AsyncSession, *, audit: AuditRecorder | None = None) -> None:
        self._session = session
        self._roles = RoleRepository(session)
        self._resources = PermissionResourceRepository(session)
        self._grants = RolePermissionRepository(session)
        self._versions = PermissionVersionRepository(session)
        self._authz = AuthorizationService(session)
        self._guard = AuditGuard(audit or NullAuditRecorder(), RESOURCE_TYPE)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    async def _load_role_id(self, *, actor: CurrentActor, role_id: int, action: AuditAction) -> int:
        """角色目标的唯一入口：授权校验 + 存在性校验。"""
        with self._guard.denial_audited(actor=actor, action=action, resource_id=role_id):
            await self._authz.assert_can_manage_roles(actor=actor)
        role = await self._roles.get(role_id)
        if role is None:
            raise NotFoundError("角色不存在")
        return role.id

    @staticmethod
    def _resolve_binary_type(kind: str) -> PermissionResourceType:
        """把路径片段（pages/menus/...）映射为资源类型。"""
        resource_type = _BINARY_TYPES.get(kind)
        if resource_type is None:
            raise BadRequestError(f"不支持的权限类别：{kind}")
        return resource_type

    async def _assert_resources_assignable(
        self, *, resource_type: PermissionResourceType, resource_ids: frozenset[int]
    ) -> None:
        """校验被授权的资源存在、有效、且类型正确。

        **类型校验不能省**：否则调用方可以把一个 PAGE 的 ID 传给
        `PUT /roles/{id}/permissions/apis`，虽然该行会落进 `role_permissions`，
        但有效权限计算按 `resource_type` 过滤，结果是"配了却没生效"——
        一种极难排查的配置失效。
        """
        if not resource_ids:
            return
        resources = await self._resources.list_by_ids(sorted(resource_ids))
        found = {resource.id for resource in resources}
        missing = resource_ids - found
        if missing:
            raise BadRequestError(f"以下资源不存在、已删除或已禁用：{sorted(missing)}")
        wrong_type = sorted(
            resource.id for resource in resources if resource.resource_type is not resource_type
        )
        if wrong_type:
            raise BadRequestError(f"以下资源不是 {resource_type.value} 类型：{wrong_type}")

    async def _assert_fields_assignable(self, *, levels: dict[int, FieldAccessLevel]) -> None:
        """校验字段资源存在、有效、且类型为 FIELD。"""
        if not levels:
            return
        resources = await self._resources.list_by_ids(sorted(levels))
        found = {resource.id for resource in resources}
        missing = set(levels) - found
        if missing:
            raise BadRequestError(f"以下字段资源不存在、已删除或已禁用：{sorted(missing)}")
        wrong_type = sorted(
            resource.id
            for resource in resources
            if resource.resource_type is not PermissionResourceType.FIELD
        )
        if wrong_type:
            raise BadRequestError(f"以下资源不是 FIELD 类型：{wrong_type}")

    async def _current_view(self, role_id: int) -> RolePermissionView:
        """读取角色当前授权视图。"""
        return RolePermissionView(
            role_id=role_id,
            page_ids=await self._grants.list_resource_ids(role_id, PermissionResourceType.PAGE),
            menu_ids=await self._grants.list_resource_ids(role_id, PermissionResourceType.MENU),
            button_ids=await self._grants.list_resource_ids(role_id, PermissionResourceType.BUTTON),
            api_ids=await self._grants.list_resource_ids(role_id, PermissionResourceType.API),
            field_levels=await self._grants.list_field_levels(role_id),
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def get(self, *, actor: CurrentActor, role_id: int) -> RolePermissionView:
        """查询角色授权（含授权校验与审计）。"""
        resolved_id = await self._load_role_id(
            actor=actor, role_id=role_id, action=AuditAction.ROLE_PERMISSION_READ
        )
        view = await self._current_view(resolved_id)
        self._guard.success(
            actor=actor,
            action=AuditAction.ROLE_PERMISSION_READ,
            resource_id=resolved_id,
            after=_snapshot_view(view),
        )
        return view

    # ------------------------------------------------------------------
    # 写入（四类二元权限）
    # ------------------------------------------------------------------
    async def replace(
        self,
        *,
        actor: CurrentActor,
        role_id: int,
        kind: str,
        resource_ids: frozenset[int],
    ) -> RolePermissionView:
        """整体替换角色在某一类别上的授权（pages / menus / buttons / apis）。"""
        resource_type = self._resolve_binary_type(kind)
        resolved_id = await self._load_role_id(
            actor=actor, role_id=role_id, action=AuditAction.ROLE_PERMISSION_UPDATE
        )
        await self._assert_resources_assignable(
            resource_type=resource_type, resource_ids=resource_ids
        )

        before, after = await self._grants.replace_resource_ids(
            resolved_id, resource_type, resource_ids
        )
        await self._versions.bump()

        self._guard.success(
            actor=actor,
            action=AuditAction.ROLE_PERMISSION_UPDATE,
            resource_id=resolved_id,
            before={"resource_type": resource_type.value, "resource_ids": sorted(before)},
            after={"resource_type": resource_type.value, "resource_ids": sorted(after)},
        )
        return await self._current_view(resolved_id)

    # ------------------------------------------------------------------
    # 写入（字段权限，携带等级）
    # ------------------------------------------------------------------
    async def replace_fields(
        self,
        *,
        actor: CurrentActor,
        role_id: int,
        levels: dict[int, FieldAccessLevel],
    ) -> RolePermissionView:
        """整体替换角色的字段权限（DD-06 冻结：携带四级取值）。"""
        resolved_id = await self._load_role_id(
            actor=actor, role_id=role_id, action=AuditAction.ROLE_PERMISSION_UPDATE
        )
        await self._assert_fields_assignable(levels=levels)

        before, after = await self._grants.replace_field_levels(resolved_id, levels)
        await self._versions.bump()

        self._guard.success(
            actor=actor,
            action=AuditAction.ROLE_PERMISSION_UPDATE,
            resource_id=resolved_id,
            before={
                "resource_type": PermissionResourceType.FIELD.value,
                "field_levels": {str(k): v.value for k, v in sorted(before.items())},
            },
            after={
                "resource_type": PermissionResourceType.FIELD.value,
                "field_levels": {str(k): v.value for k, v in sorted(after.items())},
            },
        )
        return await self._current_view(resolved_id)

    # ------------------------------------------------------------------
    # 权限预览所需：资源明细
    # ------------------------------------------------------------------
    async def list_granted_resources(
        self, *, actor: CurrentActor, role_id: int, resource_type: PermissionResourceType
    ) -> tuple[PermissionResource, ...]:
        """列出角色在指定类型上被授权的资源明细（供后台界面显示名称/路由）。"""
        resolved_id = await self._load_role_id(
            actor=actor, role_id=role_id, action=AuditAction.ROLE_PERMISSION_READ
        )
        resource_ids = await self._grants.list_resource_ids(resolved_id, resource_type)
        resources = await self._resources.list_by_ids(sorted(resource_ids))
        return tuple(sorted(resources, key=lambda resource: resource.id))


__all__ = ["RESOURCE_TYPE", "RolePermissionService", "RolePermissionView"]
