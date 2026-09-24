"""权限资源服务（Task 3.6~3.9：Page / Menu / Button / API / Field 资源 CRUD）。

Frozen / 已裁定依据
------------------
- Spec `03 §5`：Page 表示用户可以进入/查看的页面，**必须可以由后台配置**。
- Spec `03 §6` / `09 §4`：Menu 是导航结构；一个 Menu 可关联多个 Page。
- Spec `03 §7`：Button 控制页面内操作入口。
- Spec `03 §8` / `08 §10`：API Permission 是后端强制授权。
- Spec `03 §9`：Field 权限四级取值，最终策略由后端统一计算并输出。
- Spec `07 §9`：parent-child index、软删除感知唯一。
- Spec `08 §7`：角色授权端点；资源端点由 **DD-20 冻结**（`08 §7` 原缺失部分）。
- **DD-20 已冻结**：统一 `permission_resources` + 独立 `menu_pages`
  + 统一 `role_permissions`；`resource_code` **按类型**逻辑删除感知唯一；
  资源端点清单见 `docs/DECISION-REQUEST-PHASE-3.md` §5.1.1。
- **DD-06 已冻结**：FIELD 资源归属 PAGE（`owner_resource_id`）。

应用层必须校验的跨行不变量（DB 的 FK 无法表达）
--------------------------------------------
1. `BUTTON.parent_id` → 必须是 **PAGE**；
2. `MENU.parent_id` → 必须是 **MENU**；
3. `API.parent_id`（非空时）→ 必须是 **PAGE**；
4. `FIELD.owner_resource_id` → 必须是 **PAGE**。

这四条不会由数据库自动保证（FK 只约束"存在且未删除"），
因此**每个写入路径**都必须显式校验 —— 漏一条就会造出
"按钮挂在菜单下"这类形状错误数据，而前端会据此渲染出错误的导航。

形状校验的唯一来源
----------------
类型 ↔ 专属列的对应关系定义在 `app.models.permission` 的
`TYPE_REQUIRED_COLUMNS` / `TYPE_OPTIONAL_COLUMNS`，本模块**直接复用**它。
这样"数据库 CHECK"与"应用层 400"永远是同一份规则，
不会出现"CHECK 允许但服务拒绝"或反之的漂移。

资源类型不可修改
--------------
`update` **不接受** `resource_type`。原因：类型决定了资源参与哪一类
判权（PAGE 决定可进入、API 决定后端授权……），改类型等于把已有的
角色授权静默重新解释成另一种权限 —— 典型的权限放大路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditRecorder, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.db.base import utc_now
from app.models.enums import HttpMethod, PermissionResourceType, PermissionStatus
from app.models.permission import (
    TYPE_OPTIONAL_COLUMNS,
    TYPE_REQUIRED_COLUMNS,
    PermissionResource,
)
from app.repositories.permission import (
    PermissionResourceRepository,
    PermissionVersionRepository,
    RolePermissionRepository,
)
from app.services.audit_guard import AuditGuard
from app.services.authorization import AuthorizationService

#: 审计资源类型。
RESOURCE_TYPE = "PERMISSION_RESOURCE"

#: 各类型允许的父资源类型（DD-20 冻结的树形语义）。
#:
#: `None` 表示"该类型不得有父资源"。
_PARENT_TYPE_RULES: dict[PermissionResourceType, PermissionResourceType | None] = {
    PermissionResourceType.PAGE: None,
    PermissionResourceType.MENU: PermissionResourceType.MENU,
    PermissionResourceType.BUTTON: PermissionResourceType.PAGE,
    PermissionResourceType.API: PermissionResourceType.PAGE,
    PermissionResourceType.FIELD: None,  # 归属通过 owner_resource_id 表达
}

#: 参与形状校验的类型专属列（与 `app.models.permission` 保持一致）。
_SHAPE_COLUMNS: tuple[str, ...] = (
    "parent_id",
    "route_path",
    "component_path",
    "icon",
    "api_method",
    "api_path",
    "field_key",
    "owner_resource_id",
)

MAX_CODE_LENGTH = 128
MAX_NAME_LENGTH = 128
MAX_PATH_LENGTH = 255
MAX_ICON_LENGTH = 64
MAX_FIELD_KEY_LENGTH = 128


@dataclass(frozen=True, slots=True)
class ResourcePage:
    """资源分页结果。"""

    items: list[PermissionResource]
    total: int
    page_num: int
    page_size: int


@dataclass(frozen=True, slots=True)
class ResourceTreeNode:
    """资源的树节点（仅用于 `MENU` 导航树）。"""

    resource: PermissionResource
    children: tuple[ResourceTreeNode, ...]


def _snapshot(resource: PermissionResource) -> dict[str, Any]:
    """资源审计快照。"""
    return {
        "id": resource.id,
        "resource_type": resource.resource_type.value,
        "resource_code": resource.resource_code,
        "resource_name": resource.resource_name,
        "parent_id": resource.parent_id,
        "sort_order": resource.sort_order,
        "status": resource.status.value,
        "route_path": resource.route_path,
        "component_path": resource.component_path,
        "icon": resource.icon,
        "api_method": resource.api_method,
        "api_path": resource.api_path,
        "field_key": resource.field_key,
        "owner_resource_id": resource.owner_resource_id,
        "deleted_at": resource.deleted_at.isoformat() if resource.deleted_at else None,
    }


class PermissionResourceService:
    """权限资源定义的业务服务。"""

    def __init__(self, session: AsyncSession, *, audit: AuditRecorder | None = None) -> None:
        self._session = session
        self._resources = PermissionResourceRepository(session)
        self._grants = RolePermissionRepository(session)
        self._versions = PermissionVersionRepository(session)
        self._authz = AuthorizationService(session)
        self._guard = AuditGuard(audit or NullAuditRecorder(), RESOURCE_TYPE)

    # ------------------------------------------------------------------
    # 内部：授权
    # ------------------------------------------------------------------
    async def _assert_can_manage(
        self, *, actor: CurrentActor, action: AuditAction, resource_id: int | None
    ) -> None:
        """资源管理的唯一授权入口（拒绝留痕）。"""
        with self._guard.denial_audited(actor=actor, action=action, resource_id=resource_id):
            await self._authz.assert_can_manage_permission_resources(actor=actor)

    # ------------------------------------------------------------------
    # 内部：形状与引用校验
    # ------------------------------------------------------------------
    @staticmethod
    def _assert_shape(resource_type: PermissionResourceType, values: dict[str, Any]) -> None:
        """校验"类型 ↔ 专属列"形状（与数据库 CHECK 同一份规则）。

        规则来自 `app.models.permission.TYPE_REQUIRED_COLUMNS` /
        `TYPE_OPTIONAL_COLUMNS`，因此这里与 DDL 不会漂移。

        为什么要在应用层再校验一遍：数据库抛出的约束错误会被统一异常处理
        兜成 500（内部错误），而这是**调用方参数问题**，应当是 400。
        两者都要有：DB 约束是最后防线，应用层校验负责给出可用的错误信息。
        """
        required = TYPE_REQUIRED_COLUMNS[resource_type]
        optional = TYPE_OPTIONAL_COLUMNS.get(resource_type, ())
        for column in _SHAPE_COLUMNS:
            value = values.get(column)
            if column in required:
                if value is None or (isinstance(value, str) and not value.strip()):
                    raise BadRequestError(f"{resource_type.value} 类型必须提供 {column}")
            elif column not in optional and value is not None:
                raise BadRequestError(f"{resource_type.value} 类型不得携带 {column}")

    @staticmethod
    def _assert_api_fields(*, api_method: str | None, api_path: str | None) -> None:
        """API 资源的方法与路径校验（DD-20 冻结取值域）。"""
        if api_method is None or api_path is None:
            return
        if api_method not in {method.value for method in HttpMethod}:
            allowed = "/".join(method.value for method in HttpMethod)
            raise BadRequestError(f"api_method 必须是 {allowed} 之一")
        if not api_path.startswith("/"):
            raise BadRequestError("api_path 必须以 / 开头")
        if len(api_path) > MAX_PATH_LENGTH:
            raise BadRequestError(f"api_path 长度不得超过 {MAX_PATH_LENGTH}")

    @staticmethod
    def _assert_text_lengths(
        *,
        resource_code: str | None = None,
        resource_name: str | None = None,
        field_key: str | None = None,
        icon: str | None = None,
    ) -> None:
        """文本字段的长度与非空校验。"""
        if resource_code is not None:
            if not resource_code.strip():
                raise BadRequestError("resource_code 不能为空")
            if len(resource_code) > MAX_CODE_LENGTH:
                raise BadRequestError(f"resource_code 长度不得超过 {MAX_CODE_LENGTH}")
        if resource_name is not None:
            if not resource_name.strip():
                raise BadRequestError("resource_name 不能为空")
            if len(resource_name) > MAX_NAME_LENGTH:
                raise BadRequestError(f"resource_name 长度不得超过 {MAX_NAME_LENGTH}")
        if field_key is not None and len(field_key) > MAX_FIELD_KEY_LENGTH:
            raise BadRequestError(f"field_key 长度不得超过 {MAX_FIELD_KEY_LENGTH}")
        if icon is not None and len(icon) > MAX_ICON_LENGTH:
            raise BadRequestError(f"icon 长度不得超过 {MAX_ICON_LENGTH}")

    async def _assert_parent_valid(
        self,
        *,
        resource_type: PermissionResourceType,
        parent_id: int | None,
    ) -> None:
        """校验父资源的**存在性**与**类型**（DD-20 冻结的树形语义）。"""
        allowed_parent_type = _PARENT_TYPE_RULES[resource_type]
        if parent_id is None:
            return
        parent = await self._resources.get(parent_id)
        if parent is None:
            raise BadRequestError("父资源不存在或已删除")
        if allowed_parent_type is None:
            raise BadRequestError(f"{resource_type.value} 类型不允许设置父资源")
        if parent.resource_type is not allowed_parent_type:
            raise BadRequestError(
                f"{resource_type.value} 的父资源必须是 {allowed_parent_type.value}，"
                f"实际为 {parent.resource_type.value}"
            )

    async def _assert_owner_valid(
        self, *, owner_resource_id: int | None
    ) -> PermissionResource | None:
        """校验 FIELD 的归属页面必须是 PAGE 类型。"""
        if owner_resource_id is None:
            return None
        owner = await self._resources.get(owner_resource_id)
        if owner is None:
            raise BadRequestError("归属页面不存在或已删除")
        if owner.resource_type is not PermissionResourceType.PAGE:
            raise BadRequestError(
                f"FIELD 的归属资源必须是 PAGE，实际为 {owner.resource_type.value}"
            )
        return owner

    async def _assert_field_key_unique(
        self,
        *,
        owner_resource_id: int,
        field_key: str,
        exclude_resource_id: int | None = None,
    ) -> None:
        """同一归属页面下 `field_key` 必须唯一。

        INTERIM（Spec 未规定）：`(owner_resource_id, field_key)` 的唯一性
        Spec 未冻结，但重复会让"字段名 → 等级"的输出产生歧义
        （两个 FIELD 资源同名，前端拿到哪一个是实现细节）。
        因此按最小可用口径在应用层拒绝；若后续冻结为不同语义（例如
        允许同名字段分属不同场景），只需移除本校验。

        为什么不做成数据库唯一索引：DD-20 冻结的唯一键是
        `(resource_type, resource_code)`，再加一条复合唯一索引会改变
        已冻结的模型形状，超出本次授权范围。
        """
        resources = await self._resources.list_resources(
            resource_type=PermissionResourceType.FIELD, page_num=1, page_size=100
        )
        for resource in resources:
            if resource.id == exclude_resource_id:
                continue
            if resource.owner_resource_id == owner_resource_id and resource.field_key == field_key:
                raise ConflictError(f"归属页面下已存在同名字段：{field_key}")

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def get(self, *, actor: CurrentActor, resource_id: int) -> PermissionResource:
        """按 ID 读取资源。"""
        await self._assert_can_manage(
            actor=actor, action=AuditAction.PERMISSION_RESOURCE_READ, resource_id=resource_id
        )
        resource = await self._resources.get(resource_id)
        if resource is None:
            raise NotFoundError("权限资源不存在")
        return resource

    async def list_resources(
        self,
        *,
        actor: CurrentActor,
        resource_type: PermissionResourceType | None = None,
        parent_id: int | None = None,
        status: PermissionStatus | None = None,
        keyword: str | None = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> ResourcePage:
        """分页列出资源。"""
        if page_num < 1:
            raise BadRequestError("pageNum 必须大于等于 1")
        if not 1 <= page_size <= 100:
            raise BadRequestError("pageSize 必须在 1..100 之间")

        await self._assert_can_manage(
            actor=actor, action=AuditAction.PERMISSION_RESOURCE_READ, resource_id=None
        )
        items = await self._resources.list_resources(
            resource_type=resource_type,
            parent_id=parent_id,
            status=status,
            keyword=keyword,
            page_num=page_num,
            page_size=page_size,
        )
        total = await self._resources.count_resources(
            resource_type=resource_type, parent_id=parent_id, status=status, keyword=keyword
        )
        return ResourcePage(items=items, total=total, page_num=page_num, page_size=page_size)

    async def tree(
        self, *, actor: CurrentActor, resource_type: PermissionResourceType
    ) -> tuple[ResourceTreeNode, ...]:
        """构建资源树（DD-20 冻结：主要用于 `MENU` 导航树）。

        环路安全
        -------
        单纯按 `parent_id` 递归构造，一旦数据里出现环（A 的父是 B、B 的父是 A）
        就会无限递归。因此本方法按"从根 BFS + visited 去重"构造：
        任何指向已访问节点的边都会被丢弃，无法到达根的节点被提升为根。
        结果是：**即使数据损坏，本方法也一定终止**，且不静默丢失节点。
        """
        await self._assert_can_manage(
            actor=actor, action=AuditAction.PERMISSION_RESOURCE_READ, resource_id=None
        )
        # 用同一分页上限循环取完该类型的全部资源（导航树规模有限，
        # 且必须完整才能正确构树）。
        resources: list[PermissionResource] = []
        page_num = 1
        while True:
            batch = await self._resources.list_resources(
                resource_type=resource_type, page_num=page_num, page_size=100
            )
            if not batch:
                break
            resources.extend(batch)
            if len(batch) < 100:
                break
            page_num += 1

        by_id = {resource.id: resource for resource in resources}
        children_map: dict[int, list[int]] = {}
        roots: list[int] = []
        for resource in resources:
            parent_id = resource.parent_id
            if parent_id is None or parent_id not in by_id:
                roots.append(resource.id)
            else:
                children_map.setdefault(parent_id, []).append(resource.id)

        visited: set[int] = set()

        def build(resource_id: int) -> ResourceTreeNode:
            visited.add(resource_id)
            child_nodes: list[ResourceTreeNode] = []
            for child_id in children_map.get(resource_id, []):
                if child_id in visited:
                    # 环上的回边 → 丢弃该边，保证终止。
                    continue
                child_nodes.append(build(child_id))
            return ResourceTreeNode(resource=by_id[resource_id], children=tuple(child_nodes))

        nodes: list[ResourceTreeNode] = [build(root_id) for root_id in sorted(roots)]
        # 不可达根的节点（环内节点）提升为根，避免静默丢失。
        for resource_id in sorted(by_id):
            if resource_id not in visited:
                nodes.append(build(resource_id))
        return tuple(nodes)

    # ------------------------------------------------------------------
    # Menu → Page 关联
    # ------------------------------------------------------------------
    async def list_menu_pages(
        self, *, actor: CurrentActor, menu_id: int
    ) -> tuple[PermissionResource, ...]:
        """读取 Menu 关联的 Page 列表。"""
        await self._assert_can_manage(
            actor=actor, action=AuditAction.PERMISSION_RESOURCE_READ, resource_id=menu_id
        )
        menu = await self._resources.get(menu_id)
        if menu is None:
            raise NotFoundError("权限资源不存在")
        if menu.resource_type is not PermissionResourceType.MENU:
            raise BadRequestError("只有 MENU 资源可以关联 Page")
        page_ids = await self._resources.list_menu_page_ids(menu_id)
        pages = await self._resources.list_by_ids(sorted(page_ids))
        return tuple(sorted(pages, key=lambda page: page.id))

    async def set_menu_pages(
        self,
        *,
        actor: CurrentActor,
        menu_id: int,
        page_ids: frozenset[int],
    ) -> tuple[frozenset[int], frozenset[int]]:
        """整体替换 Menu → Page 关联（`00 §1#4` 多对多）。"""
        await self._assert_can_manage(
            actor=actor, action=AuditAction.PERMISSION_RESOURCE_UPDATE, resource_id=menu_id
        )
        menu = await self._resources.get(menu_id)
        if menu is None:
            raise NotFoundError("权限资源不存在")
        if menu.resource_type is not PermissionResourceType.MENU:
            raise BadRequestError("只有 MENU 资源可以关联 Page")

        if page_ids:
            pages = await self._resources.list_by_ids(sorted(page_ids))
            if len(pages) != len(page_ids):
                raise BadRequestError("包含不存在或已删除的 Page")
            wrong_type = [
                page.id for page in pages if page.resource_type is not PermissionResourceType.PAGE
            ]
            if wrong_type:
                raise BadRequestError(f"以下资源不是 PAGE 类型：{sorted(wrong_type)}")

        before, after = await self._resources.replace_menu_pages(menu_id, page_ids)
        # 导航可见性变化会影响前端菜单渲染（`09 §5`），但**不改变**任何
        # 后端判权结果（判权只认 Page）。仍递增版本，让前端及时刷新。
        await self._versions.bump()
        self._guard.success(
            actor=actor,
            action=AuditAction.PERMISSION_RESOURCE_UPDATE,
            resource_id=menu_id,
            before={"page_ids": sorted(before)},
            after={"page_ids": sorted(after)},
        )
        return before, after

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------
    async def create(
        self,
        *,
        actor: CurrentActor,
        resource_type: PermissionResourceType,
        resource_code: str,
        resource_name: str,
        parent_id: int | None = None,
        sort_order: int = 0,
        status: PermissionStatus = PermissionStatus.ACTIVE,
        route_path: str | None = None,
        component_path: str | None = None,
        icon: str | None = None,
        api_method: str | None = None,
        api_path: str | None = None,
        field_key: str | None = None,
        owner_resource_id: int | None = None,
    ) -> PermissionResource:
        """创建权限资源。"""
        await self._assert_can_manage(
            actor=actor, action=AuditAction.PERMISSION_RESOURCE_CREATE, resource_id=None
        )
        self._assert_text_lengths(
            resource_code=resource_code,
            resource_name=resource_name,
            field_key=field_key,
            icon=icon,
        )
        values: dict[str, Any] = {
            "parent_id": parent_id,
            "route_path": route_path,
            "component_path": component_path,
            "icon": icon,
            "api_method": api_method,
            "api_path": api_path,
            "field_key": field_key,
            "owner_resource_id": owner_resource_id,
        }
        self._assert_shape(resource_type, values)
        self._assert_api_fields(api_method=api_method, api_path=api_path)
        await self._assert_parent_valid(resource_type=resource_type, parent_id=parent_id)
        await self._assert_owner_valid(owner_resource_id=owner_resource_id)
        if resource_type is PermissionResourceType.FIELD and owner_resource_id is not None:
            assert field_key is not None  # 由 _assert_shape 保证
            await self._assert_field_key_unique(
                owner_resource_id=owner_resource_id, field_key=field_key
            )

        if await self._resources.get_by_code(resource_type, resource_code) is not None:
            raise ConflictError(f"该类型下资源编码已存在：{resource_type.value}/{resource_code}")

        resource = PermissionResource(
            resource_type=resource_type,
            resource_code=resource_code,
            resource_name=resource_name,
            parent_id=parent_id,
            sort_order=sort_order,
            status=status,
            route_path=route_path,
            component_path=component_path,
            icon=icon,
            api_method=api_method,
            api_path=api_path,
            field_key=field_key,
            owner_resource_id=owner_resource_id,
        )
        await self._resources.add(resource)
        self._guard.success(
            actor=actor,
            action=AuditAction.PERMISSION_RESOURCE_CREATE,
            resource_id=resource.id,
            after=_snapshot(resource),
        )
        return resource

    # ------------------------------------------------------------------
    # 修改
    # ------------------------------------------------------------------
    async def update(
        self,
        *,
        actor: CurrentActor,
        resource_id: int,
        resource_name: str | None = None,
        sort_order: int | None = None,
        status: PermissionStatus | None = None,
        route_path: str | None = None,
        component_path: str | None = None,
        icon: str | None = None,
        api_method: str | None = None,
        api_path: str | None = None,
        field_key: str | None = None,
    ) -> PermissionResource:
        """修改资源（**不允许**修改 `resource_type` / `resource_code` / 父子关系）。

        - `resource_type`：改类型等于把已有授权静默重新解释成另一类权限。
        - `resource_code`：编码是资源在审计与前端契约中的稳定标识。
        - `parent_id` / `owner_resource_id`：调整树形归属需要连带校验
          子树形状与授权影响，属于独立的"移动资源"操作，
          不在本次 DD-20 冻结的端点范围内。

        因此本方法只更新展示属性与状态。
        """
        await self._assert_can_manage(
            actor=actor, action=AuditAction.PERMISSION_RESOURCE_UPDATE, resource_id=resource_id
        )
        resource = await self._resources.get(resource_id)
        if resource is None:
            raise NotFoundError("权限资源不存在")

        self._assert_text_lengths(resource_name=resource_name, field_key=field_key, icon=icon)

        before = _snapshot(resource)
        status_changed = status is not None and status is not resource.status

        if resource_name is not None:
            resource.resource_name = resource_name
        if sort_order is not None:
            resource.sort_order = sort_order
        if status is not None:
            resource.status = status
        if route_path is not None:
            resource.route_path = route_path
        if component_path is not None:
            resource.component_path = component_path
        if icon is not None:
            resource.icon = icon
        if api_method is not None:
            resource.api_method = api_method
        if api_path is not None:
            resource.api_path = api_path
        if field_key is not None:
            resource.field_key = field_key

        # 修改后必须重新满足形状约束（例如把 PAGE 的 route_path 置空会被拒绝）。
        self._assert_shape(
            resource.resource_type,
            {
                "parent_id": resource.parent_id,
                "route_path": resource.route_path,
                "component_path": resource.component_path,
                "icon": resource.icon,
                "api_method": resource.api_method,
                "api_path": resource.api_path,
                "field_key": resource.field_key,
                "owner_resource_id": resource.owner_resource_id,
            },
        )
        self._assert_api_fields(api_method=resource.api_method, api_path=resource.api_path)
        if resource.resource_type is PermissionResourceType.FIELD:
            if resource.owner_resource_id is None or resource.field_key is None:
                raise BadRequestError("FIELD 资源必须同时具备 field_key 与 owner_resource_id")
            await self._assert_field_key_unique(
                owner_resource_id=resource.owner_resource_id,
                field_key=resource.field_key,
                exclude_resource_id=resource.id,
            )

        await self._session.flush()

        if status_changed:
            # 资源被禁用 / 启用会直接改变所有被授权角色的有效权限
            # （有效资源过滤要求 status = ACTIVE）→ 必须递增版本（Spec `11 §2`）。
            await self._versions.bump()

        self._guard.success(
            actor=actor,
            action=AuditAction.PERMISSION_RESOURCE_UPDATE,
            resource_id=resource.id,
            before=before,
            after=_snapshot(resource),
        )
        return resource

    # ------------------------------------------------------------------
    # 逻辑删除
    # ------------------------------------------------------------------
    async def delete(self, *, actor: CurrentActor, resource_id: int) -> PermissionResource:
        """逻辑删除资源（引用检查）。

        引用来源三类，**一律拒绝**而不是级联清理：

        1. 子资源（`parent_id` / `owner_resource_id` 指向它）；
        2. `menu_pages` 关联；
        3. 角色授权（`role_permissions` / `role_field_permissions`）。

        为什么这里拒绝而角色删除时清理从属授权：资源是**被授权方引用**的
        目标，删除它等于让"这些角色的这条授权"失去意义；静默清理会改变
        多个角色的有效权限（影响面不可见）。拒绝则强制管理员显式决定。
        这与 Spec `03 §4`"删除父角色导致隐式错误"的取向一致。
        """
        await self._assert_can_manage(
            actor=actor, action=AuditAction.PERMISSION_RESOURCE_DELETE, resource_id=resource_id
        )
        resource = await self._resources.get(resource_id)
        if resource is None:
            raise NotFoundError("权限资源不存在")

        with self._guard.denial_audited(
            actor=actor, action=AuditAction.PERMISSION_RESOURCE_DELETE, resource_id=resource.id
        ):
            children = await self._resources.count_child_references(resource.id)
            if children:
                raise ConflictError(f"仍有 {children} 个子资源引用该资源，请先处理子资源后再删除")
            menu_refs = await self._resources.count_menu_page_references(resource.id)
            if menu_refs:
                raise ConflictError(f"该资源仍被 {menu_refs} 条菜单-页面关联引用，请先解除关联")
            grants = await self._grants.count_roles_for_resource(resource.id)
            if grants:
                raise ConflictError(f"该资源仍被 {grants} 条角色授权引用，请先撤销授权后再删除")

        before = _snapshot(resource)
        resource.status = PermissionStatus.DISABLED
        resource.deleted_at = utc_now()
        await self._session.flush()

        await self._versions.bump()
        self._guard.success(
            actor=actor,
            action=AuditAction.PERMISSION_RESOURCE_DELETE,
            resource_id=resource.id,
            before=before,
            after=_snapshot(resource),
        )
        return resource


__all__ = [
    "RESOURCE_TYPE",
    "PermissionResourceService",
    "ResourcePage",
    "ResourceTreeNode",
]
