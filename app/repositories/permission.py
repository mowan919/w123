"""权限资源与角色授权的数据访问。

Frozen / 已裁定依据
------------------
- Spec `07 §5`：`role_permissions` 为核心表；权限拆分为
  page/menu/button/api/field 关联形态。
- Spec `03 §5~§9`：五类资源语义；Field 为四级取值。
- Spec `07 §9`：FK / index / unique / soft-delete-aware unique / parent-child index。
- Spec `10 §10`：范围与可见性约束必须下推 SQL，禁止"先查全部再内存过滤"。
- Spec `11 §3`：权限修改属并发保护重点 → 版本递增必须走单条原子 SQL。
- **DD-20 / DD-06 已冻结**：统一资源表 + 独立 Menu→Page 关联 + 统一授权表
  + 专用字段授权表。

关键正确性要点（易错，故显式说明）
------------------------------
1. **按类型替换授权**：`PUT /roles/{id}/permissions/pages` 只能影响该角色的
   **PAGE 授权**。若实现成"先清空该角色全部授权再写入"，会静默清掉
   API / BUTTON 授权 —— 那是**权限缩小**（可用性事故），
   而反过来漏清又会造成**权限放大**。因此所有替换都带 `resource_type` 过滤。
2. **只在未删除且 ACTIVE 的资源上判权**：删除或禁用的资源不得继续授权，
   否则"删除资源"这一动作无法真正收回权限（`11 §5` 取向）。
3. **版本递增用单条 UPDATE**：`version = version + 1` 由数据库完成，
   避免"读-改-写"在并发下产生重复版本号（`11 §3`）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import CTE, ColumnElement, Select, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    FieldAccessLevel,
    PermissionResourceType,
    PermissionStatus,
    RoleStatus,
)
from app.models.permission import (
    MenuPage,
    PermissionResource,
    PermissionVersion,
    RoleFieldPermission,
    RolePermission,
)
from app.models.role import Role, RoleInheritance, UserRole

#: `_apply_filters` 的泛型参数：保证过滤后语句的行类型不丢失。
_RowT = TypeVar("_RowT", bound=tuple[Any, ...])

#: 权限版本桶标识 —— DD-04 未冻结其命名规范，Phase 3 只用这一个桶。
#: 登记为 INTERIM，Phase 9 冻结 Redis Key 命名时一并确定。
GLOBAL_SCOPE = "GLOBAL"


def _live_resource_filter() -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    """有效资源过滤条件：未删除且 ACTIVE。

    单独抽出来是为了让"哪些资源算有效"只有一处定义 ——
    权限计算、引用检查、授权校验必须用**同一口径**，
    否则会出现"判权时算它有效、展示时算它无效"的不一致。

    返回元组而非单个条件，便于直接展开为 `.where(*_live_resource_filter())`。
    """
    return (
        PermissionResource.deleted_at.is_(None),
        PermissionResource.status == PermissionStatus.ACTIVE,
    )


class PermissionResourceRepository:
    """权限资源仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 单条 / 批量读取
    # ------------------------------------------------------------------
    async def get(
        self, resource_id: int, *, include_deleted: bool = False
    ) -> PermissionResource | None:
        """按 ID 读取资源；默认排除逻辑删除。"""
        stmt = select(PermissionResource).where(PermissionResource.id == resource_id)
        if not include_deleted:
            stmt = stmt.where(PermissionResource.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_code(
        self, resource_type: PermissionResourceType, resource_code: str
    ) -> PermissionResource | None:
        """按 `(类型, 编码)` 读取**未删除**资源（唯一性预校验用）。"""
        stmt = select(PermissionResource).where(
            PermissionResource.resource_type == resource_type,
            PermissionResource.resource_code == resource_code,
            PermissionResource.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_ids(
        self, resource_ids: Sequence[int], *, only_live: bool = True
    ) -> list[PermissionResource]:
        """按 ID 批量读取资源。"""
        if not resource_ids:
            return []
        stmt = select(PermissionResource).where(
            PermissionResource.id.in_(sorted(set(resource_ids)))
        )
        if only_live:
            stmt = stmt.where(*_live_resource_filter())
        return list((await self._session.execute(stmt)).scalars().all())

    async def existing_live_ids(self, resource_ids: frozenset[int]) -> frozenset[int]:
        """返回给定集合中**存在且有效**（未删除、ACTIVE）的资源 ID。"""
        if not resource_ids:
            return frozenset()
        stmt = select(PermissionResource.id).where(
            PermissionResource.id.in_(sorted(resource_ids)),
            *_live_resource_filter(),
        )
        return frozenset((await self._session.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    async def add(self, resource: PermissionResource) -> PermissionResource:
        """新增资源并 flush（拿到数据库约束校验结果）。"""
        self._session.add(resource)
        await self._session.flush()
        return resource

    # ------------------------------------------------------------------
    # 列表 / 分页
    # ------------------------------------------------------------------
    async def list_resources(
        self,
        *,
        resource_type: PermissionResourceType | None = None,
        parent_id: int | None = None,
        status: PermissionStatus | None = None,
        keyword: str | None = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> list[PermissionResource]:
        """分页列出资源（未删除）。"""
        stmt = (
            select(PermissionResource)
            .where(PermissionResource.deleted_at.is_(None))
            .order_by(PermissionResource.sort_order, PermissionResource.id)
            .offset((page_num - 1) * page_size)
            .limit(page_size)
        )
        stmt = self._apply_filters(
            stmt, resource_type=resource_type, parent_id=parent_id, status=status, keyword=keyword
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_resources(
        self,
        *,
        resource_type: PermissionResourceType | None = None,
        parent_id: int | None = None,
        status: PermissionStatus | None = None,
        keyword: str | None = None,
    ) -> int:
        """统计资源数量（与 `list_resources` 同口径）。"""
        stmt = (
            select(func.count())
            .select_from(PermissionResource)
            .where(PermissionResource.deleted_at.is_(None))
        )
        stmt = self._apply_filters(
            stmt, resource_type=resource_type, parent_id=parent_id, status=status, keyword=keyword
        )
        return int((await self._session.execute(stmt)).scalar_one())

    @staticmethod
    def _apply_filters(
        stmt: Select[_RowT],
        *,
        resource_type: PermissionResourceType | None,
        parent_id: int | None,
        status: PermissionStatus | None,
        keyword: str | None,
    ) -> Select[_RowT]:
        """把可选过滤条件附加到语句上。

        `parent_id` 语义说明：调用方传 `None` 表示"不过滤"，
        传 `0` 表示"只看顶级（parent_id IS NULL）"。
        用 `0` 而不是 `None` 表达"顶级"，是因为 `None` 已被用作"不过滤"，
        而 Snowflake ID 恒为正数，`0` 不可能与真实资源 ID 冲突。
        """
        if resource_type is not None:
            stmt = stmt.where(PermissionResource.resource_type == resource_type)
        if parent_id is not None:
            stmt = (
                stmt.where(PermissionResource.parent_id.is_(None))
                if parent_id == 0
                else stmt.where(PermissionResource.parent_id == parent_id)
            )
        if status is not None:
            stmt = stmt.where(PermissionResource.status == status)
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    PermissionResource.resource_code.ilike(pattern),
                    PermissionResource.resource_name.ilike(pattern),
                )
            )
        return stmt

    # ------------------------------------------------------------------
    # 树
    # ------------------------------------------------------------------
    def _subtree_cte(self, root_id: int) -> CTE:
        """以 root 为根、仅未删除节点的子树递归 CTE（`UNION` 保环路终止）。"""
        base = (
            select(PermissionResource.id.label("id"))
            .where(PermissionResource.id == root_id, PermissionResource.deleted_at.is_(None))
            .cte("resource_subtree", recursive=True)
        )
        children = (
            select(PermissionResource.id)
            .join(base, PermissionResource.parent_id == base.c.id)
            .where(PermissionResource.deleted_at.is_(None))
        )
        return base.union(children)

    async def descendant_ids(self, root_id: int, *, include_self: bool = True) -> frozenset[int]:
        """资源子树的全部后代 ID（未删除）。"""
        subtree = self._subtree_cte(root_id)
        stmt = select(subtree.c.id)
        if not include_self:
            stmt = stmt.where(subtree.c.id != root_id)
        return frozenset((await self._session.execute(stmt)).scalars().all())

    async def count_children(self, resource_id: int) -> int:
        """未删除的直接子资源数量。"""
        stmt = (
            select(func.count())
            .select_from(PermissionResource)
            .where(
                PermissionResource.parent_id == resource_id,
                PermissionResource.deleted_at.is_(None),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------
    # Menu → Page 关联（00 §1#4 多对多）
    # ------------------------------------------------------------------
    async def list_menu_page_ids(self, menu_id: int) -> frozenset[int]:
        """读取 Menu 关联的全部 Page ID。"""
        stmt = select(MenuPage.page_id).where(MenuPage.menu_id == menu_id)
        return frozenset((await self._session.execute(stmt)).scalars().all())

    async def list_menu_page_map(self, menu_ids: Sequence[int]) -> dict[int, frozenset[int]]:
        """批量读取多个 Menu 关联的 Page ID（`Phase 8` 权限契约用）。

        为什么需要批量版本：`/auth/permissions` 要为每个已授权菜单输出
        其可访问页面，逐菜单调用 `list_menu_page_ids` 会退化成 N 次查询
        （N = 用户可见菜单数），而这是**每次打开后台首页**都会走的路径。
        一条 `IN (...)` 查询即可，语义与单条版本完全一致。

        返回的字典只包含**有关联行**的菜单；调用方对缺席的菜单按空集合处理。
        """
        if not menu_ids:
            return {}
        stmt = select(MenuPage.menu_id, MenuPage.page_id).where(
            MenuPage.menu_id.in_(sorted(set(menu_ids)))
        )
        result: dict[int, set[int]] = {}
        for menu_id, page_id in (await self._session.execute(stmt)).all():
            result.setdefault(int(menu_id), set()).add(int(page_id))
        return {menu_id: frozenset(page_ids) for menu_id, page_ids in result.items()}

    async def list_all_live(
        self, *, resource_type: PermissionResourceType
    ) -> list[PermissionResource]:
        """列出某类型的**全部有效资源**（未删除 + ACTIVE），按排序值返回。

        用途单一：SUPER_ADMIN 的权限契约。`10 §3` 冻结的超管 bypass
        意味着"有效权限 = 全部资源"，若仍按 `role_permissions` 逐条查询，
        超管拿到的会是**空集合**（超管恰恰不需要被逐条授权），
        前端于是渲染出一个空后台 —— 那是对真实授权状态的错误表述。

        返回不分页：资源定义属**配置面**，规模由管理员控制，
        与 `PermissionResourceService.tree`（构树时必须完整）同一前提。
        """
        stmt = (
            select(PermissionResource)
            .where(
                PermissionResource.resource_type == resource_type,
                *_live_resource_filter(),
            )
            .order_by(PermissionResource.sort_order, PermissionResource.id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def replace_menu_pages(
        self, menu_id: int, page_ids: frozenset[int]
    ) -> tuple[frozenset[int], frozenset[int]]:
        """整体替换 Menu → Page 关联。

        Returns:
            (before, after)，供审计 before_data / after_data 使用。
        """
        before = await self.list_menu_page_ids(menu_id)
        to_remove = before - page_ids
        to_add = page_ids - before

        if to_remove:
            await self._session.execute(
                delete(MenuPage).where(
                    MenuPage.menu_id == menu_id,
                    MenuPage.page_id.in_(sorted(to_remove)),
                )
            )
        for page_id in sorted(to_add):
            self._session.add(MenuPage(menu_id=menu_id, page_id=page_id))
        await self._session.flush()
        return before, frozenset(page_ids)

    async def clear_menu_pages(self, menu_id: int) -> frozenset[int]:
        """清空 Menu → Page 关联，返回被清除的集合。"""
        before = await self.list_menu_page_ids(menu_id)
        if before:
            await self._session.execute(delete(MenuPage).where(MenuPage.menu_id == menu_id))
            await self._session.flush()
        return before

    # ------------------------------------------------------------------
    # 引用检查（资源逻辑删除前）
    # ------------------------------------------------------------------
    async def count_child_references(self, resource_id: int) -> int:
        """仍有未删除子资源引用本资源的数量。

        含 `parent_id` 与 `owner_resource_id` 两种引用方向：
        FIELD 通过 `owner_resource_id` 指向 PAGE，也是"子资源"。
        """
        stmt = (
            select(func.count())
            .select_from(PermissionResource)
            .where(
                PermissionResource.deleted_at.is_(None),
                PermissionResource.id != resource_id,
                or_(
                    PermissionResource.parent_id == resource_id,
                    PermissionResource.owner_resource_id == resource_id,
                ),
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_menu_page_references(self, resource_id: int) -> int:
        """仍被 Menu→Page 关联引用的次数。"""
        stmt = (
            select(func.count())
            .select_from(MenuPage)
            .where(or_(MenuPage.menu_id == resource_id, MenuPage.page_id == resource_id))
        )
        return int((await self._session.execute(stmt)).scalar_one())


class RolePermissionRepository:
    """角色授权仓储（`role_permissions` + `role_field_permissions`）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    async def list_resource_ids(
        self, role_id: int, resource_type: PermissionResourceType
    ) -> frozenset[int]:
        """读取角色在**指定类型**上的全部授权资源 ID。

        只返回未删除且 ACTIVE 的资源（见模块说明第 2 点）。
        """
        stmt = (
            select(RolePermission.resource_id)
            .join(PermissionResource, PermissionResource.id == RolePermission.resource_id)
            .where(
                RolePermission.role_id == role_id,
                PermissionResource.resource_type == resource_type,
                *_live_resource_filter(),
            )
        )
        return frozenset((await self._session.execute(stmt)).scalars().all())

    async def list_resource_ids_for_roles(
        self, role_ids: Sequence[int], resource_type: PermissionResourceType
    ) -> frozenset[int]:
        """批量：多个角色在指定类型上的授权资源 ID 并集（有效权限计算用）。"""
        if not role_ids:
            return frozenset()
        stmt = (
            select(RolePermission.resource_id)
            .join(PermissionResource, PermissionResource.id == RolePermission.resource_id)
            .where(
                RolePermission.role_id.in_(sorted(set(role_ids))),
                PermissionResource.resource_type == resource_type,
                *_live_resource_filter(),
            )
        )
        return frozenset((await self._session.execute(stmt)).scalars().all())

    async def list_field_levels(self, role_id: int) -> dict[int, FieldAccessLevel]:
        """读取角色的字段等级映射（仅有效 FIELD 资源）。"""
        stmt = (
            select(RoleFieldPermission.field_id, RoleFieldPermission.access_level)
            .join(PermissionResource, PermissionResource.id == RoleFieldPermission.field_id)
            .where(
                RoleFieldPermission.role_id == role_id,
                PermissionResource.resource_type == PermissionResourceType.FIELD,
                *_live_resource_filter(),
            )
        )
        rows = (await self._session.execute(stmt)).all()
        return {int(field_id): level for field_id, level in rows}

    async def list_field_levels_for_roles(
        self, role_ids: Sequence[int]
    ) -> list[tuple[int, FieldAccessLevel]]:
        """批量：多角色的字段等级**全部**条目（合并由引擎按"最宽松者胜"完成）。

        返回原始条目而非合并结果，是为了让合并规则只有一处实现
        （`app.models.enums.most_permissive_field_level`），
        避免"仓储里一套、服务里一套"的双份真相。
        """
        if not role_ids:
            return []
        stmt = (
            select(RoleFieldPermission.field_id, RoleFieldPermission.access_level)
            .join(PermissionResource, PermissionResource.id == RoleFieldPermission.field_id)
            .where(
                RoleFieldPermission.role_id.in_(sorted(set(role_ids))),
                PermissionResource.resource_type == PermissionResourceType.FIELD,
                *_live_resource_filter(),
            )
        )
        return [
            (int(field_id), level) for field_id, level in (await self._session.execute(stmt)).all()
        ]

    # ------------------------------------------------------------------
    # 写入（整体替换，按类型隔离）
    # ------------------------------------------------------------------
    async def replace_resource_ids(
        self,
        role_id: int,
        resource_type: PermissionResourceType,
        resource_ids: frozenset[int],
    ) -> tuple[frozenset[int], frozenset[int]]:
        """整体替换角色在**指定类型**上的授权（其余类型不受影响）。

        Returns:
            (before, after)，供审计使用。
        """
        before = await self.list_resource_ids(role_id, resource_type)
        to_remove = before - resource_ids
        to_add = resource_ids - before

        if to_remove:
            await self._session.execute(
                delete(RolePermission).where(
                    RolePermission.role_id == role_id,
                    RolePermission.resource_id.in_(sorted(to_remove)),
                )
            )
        for resource_id in sorted(to_add):
            self._session.add(RolePermission(role_id=role_id, resource_id=resource_id))
        await self._session.flush()
        return before, frozenset(resource_ids)

    async def replace_field_levels(
        self, role_id: int, levels: dict[int, FieldAccessLevel]
    ) -> tuple[dict[int, FieldAccessLevel], dict[int, FieldAccessLevel]]:
        """整体替换角色的字段等级映射。

        Returns:
            (before, after)，供审计使用。
        """
        before = await self.list_field_levels(role_id)

        to_remove = set(before) - set(levels)
        if to_remove:
            await self._session.execute(
                delete(RoleFieldPermission).where(
                    RoleFieldPermission.role_id == role_id,
                    RoleFieldPermission.field_id.in_(sorted(to_remove)),
                )
            )
        # 已存在且等级未变的行不动；等级变化的行更新；新行插入。
        for field_id, level in levels.items():
            if before.get(field_id) == level:
                continue
            if field_id in before:
                await self._session.execute(
                    update(RoleFieldPermission)
                    .where(
                        RoleFieldPermission.role_id == role_id,
                        RoleFieldPermission.field_id == field_id,
                    )
                    .values(access_level=level)
                )
            else:
                self._session.add(
                    RoleFieldPermission(role_id=role_id, field_id=field_id, access_level=level)
                )
        await self._session.flush()
        return before, dict(levels)

    async def clear_field_levels(self, role_id: int) -> dict[int, FieldAccessLevel]:
        """清空角色的字段等级（资源删除时的回收路径）。"""
        before = await self.list_field_levels(role_id)
        if before:
            await self._session.execute(
                delete(RoleFieldPermission).where(RoleFieldPermission.role_id == role_id)
            )
            await self._session.flush()
        return before

    async def delete_all_for_role(
        self, role_id: int
    ) -> tuple[frozenset[int], dict[int, FieldAccessLevel]]:
        """删除角色**全部**授权（角色自身被删除时调用）。

        ⚠️ 这是唯一一个刻意跨类型清除的入口：其余所有写入都必须按类型隔离。
        命名上与其他 `replace_*` 区分开，避免被误用于常规授权更新。
        """
        before_resources = frozenset(
            (
                await self._session.execute(
                    select(RolePermission.resource_id).where(RolePermission.role_id == role_id)
                )
            )
            .scalars()
            .all()
        )
        before_fields = await self.list_field_levels(role_id)
        await self._session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
        await self._session.execute(
            delete(RoleFieldPermission).where(RoleFieldPermission.role_id == role_id)
        )
        await self._session.flush()
        return before_resources, before_fields

    # ------------------------------------------------------------------
    # 引用检查
    # ------------------------------------------------------------------
    async def count_roles_for_resource(self, resource_id: int) -> int:
        """仍被角色授权的引用数量（资源删除前的引用检查）。

        同时统计 `role_permissions` 与 `role_field_permissions` ——
        两者都是"角色 → 资源"的引用。
        """
        resource_count = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(RolePermission)
                    .where(RolePermission.resource_id == resource_id)
                )
            ).scalar_one()
        )
        field_count = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(RoleFieldPermission)
                    .where(RoleFieldPermission.field_id == resource_id)
                )
            ).scalar_one()
        )
        return resource_count + field_count

    async def list_role_ids_for_resource(self, resource_id: int) -> frozenset[int]:
        """反查哪些角色被授予了该资源（含字段授权）。"""
        stmt = select(RolePermission.role_id).where(RolePermission.resource_id == resource_id)
        role_ids = set((await self._session.execute(stmt)).scalars().all())
        stmt_fields = select(RoleFieldPermission.role_id).where(
            RoleFieldPermission.field_id == resource_id
        )
        role_ids.update((await self._session.execute(stmt_fields)).scalars().all())
        return frozenset(int(role_id) for role_id in role_ids)

    async def list_granted_role_ids_for_roles(self, role_ids: Sequence[int]) -> frozenset[int]:
        """给定角色集合中，**实际被授予过任何资源**的角色 ID。

        用于角色删除前的引用检查（避免逐个角色查两次）。
        """
        if not role_ids:
            return frozenset()
        ids = sorted(set(role_ids))
        role_ids_with_resources = set(
            (
                await self._session.execute(
                    select(RolePermission.role_id).where(RolePermission.role_id.in_(ids))
                )
            )
            .scalars()
            .all()
        )
        role_ids_with_fields = set(
            (
                await self._session.execute(
                    select(RoleFieldPermission.role_id).where(RoleFieldPermission.role_id.in_(ids))
                )
            )
            .scalars()
            .all()
        )
        return frozenset(int(x) for x in (role_ids_with_resources | role_ids_with_fields))


class PermissionVersionRepository:
    """权限版本仓储（单调递增计数器）。

    DD-04 未冻结：本类只提供"取值 + 递增"能力，不承担任何缓存语义。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, scope: str = GLOBAL_SCOPE) -> int:
        """读取当前版本号；桶不存在时返回 0（尚未发生任何权限变更）。"""
        value = (
            await self._session.execute(
                select(PermissionVersion.version).where(PermissionVersion.scope == scope)
            )
        ).scalar_one_or_none()
        return int(value) if value is not None else 0

    async def bump(self, scope: str = GLOBAL_SCOPE) -> int:
        """递增版本号并返回新值。

        单条 `INSERT ... ON CONFLICT DO UPDATE SET version = version + 1`
        完成：由数据库保证原子性，并发调用不会产生重复版本号
        （Spec `11 §3` 把"权限修改"列为并发保护重点）。
        """
        stmt = (
            pg_insert(PermissionVersion)
            .values(scope=scope, version=1, updated_at=func.now())
            .on_conflict_do_update(
                index_elements=[PermissionVersion.scope],
                set_={
                    "version": PermissionVersion.version + 1,
                    "updated_at": func.now(),
                },
            )
            .returning(PermissionVersion.version)
        )
        return int((await self._session.execute(stmt)).scalar_one())


# ---------------------------------------------------------------------------
# 角色继承（DD-05 已冻结）
# ---------------------------------------------------------------------------
class RoleInheritanceRepository:
    """角色继承关系仓储（邻接表 + 递归 CTE 展开）。

    展开方式与 `app/repositories/department.py` 的部门子树保持同一模式：
    递归 CTE 使用 `UNION`（去重）而非 `UNION ALL`，
    因此即使数据中出现父子环也能自然终止，不会无限递归（`03 §4`）。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    async def get(self, *, parent_role_id: int, child_role_id: int) -> RoleInheritance | None:
        """读取单条继承关系。"""
        stmt = select(RoleInheritance).where(
            RoleInheritance.parent_role_id == parent_role_id,
            RoleInheritance.child_role_id == child_role_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_relations_for_role(self, role_id: int) -> list[RoleInheritance]:
        """读取与该角色相关的全部继承关系（作为父或子）。"""
        stmt = select(RoleInheritance).where(
            or_(
                RoleInheritance.parent_role_id == role_id,
                RoleInheritance.child_role_id == role_id,
            )
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_relations_for_roles(self, role_ids: Sequence[int]) -> frozenset[tuple[int, int]]:
        """批量读取**仅涉及给定角色集合内部**的继承边（供权限预览展示继承链）。

        单条查询取回，避免按角色逐个查（权限预览是显式触发的低频操作，
        但仍不应退化成 N 次查询）。
        """
        if not role_ids:
            return frozenset()
        ids = sorted(set(role_ids))
        stmt = select(RoleInheritance.parent_role_id, RoleInheritance.child_role_id).where(
            RoleInheritance.parent_role_id.in_(ids),
            RoleInheritance.child_role_id.in_(ids),
        )
        return frozenset(
            (int(parent_role_id), int(child_role_id))
            for parent_role_id, child_role_id in (await self._session.execute(stmt)).all()
        )

    async def count_references(self, role_id: int) -> int:
        """该角色被继承关系引用的次数（删除角色前的引用检查）。"""
        stmt = (
            select(func.count())
            .select_from(RoleInheritance)
            .where(
                or_(
                    RoleInheritance.parent_role_id == role_id,
                    RoleInheritance.child_role_id == role_id,
                )
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_references_for_roles(self, role_ids: Sequence[int]) -> frozenset[int]:
        """批量：给定角色集合中**被继承关系引用过**的角色 ID。"""
        if not role_ids:
            return frozenset()
        ids = sorted(set(role_ids))
        stmt = select(RoleInheritance.parent_role_id, RoleInheritance.child_role_id).where(
            or_(
                RoleInheritance.parent_role_id.in_(ids),
                RoleInheritance.child_role_id.in_(ids),
            )
        )
        referenced: set[int] = set()
        target = set(ids)
        for parent_role_id, child_role_id in (await self._session.execute(stmt)).all():
            for value in (int(parent_role_id), int(child_role_id)):
                if value in target:
                    referenced.add(value)
        return frozenset(referenced)

    async def direct_parent_ids(self, role_id: int) -> frozenset[int]:
        """直接父角色 ID（该角色直接继承的角色）。"""
        stmt = select(RoleInheritance.parent_role_id).where(
            RoleInheritance.child_role_id == role_id
        )
        return frozenset((await self._session.execute(stmt)).scalars().all())

    async def direct_child_ids(self, role_id: int) -> frozenset[int]:
        """直接子角色 ID（直接继承该角色的角色）。"""
        stmt = select(RoleInheritance.child_role_id).where(
            RoleInheritance.parent_role_id == role_id
        )
        return frozenset((await self._session.execute(stmt)).scalars().all())

    def _ancestor_edges_cte(self, role_ids: Sequence[int]) -> CTE:
        """构造"从给定角色向上走到祖先"的边集合 CTE。

        返回的是**边**（child → parent）而非节点，因为后续需要
        在应用层按边做 BFS 并同时计算深度（深度上限 fail-closed）。
        `union` 去重保证环路时收敛。
        """
        base = (
            select(
                RoleInheritance.child_role_id.label("child_role_id"),
                RoleInheritance.parent_role_id.label("parent_role_id"),
            )
            .where(RoleInheritance.child_role_id.in_(sorted(set(role_ids))))
            .cte("role_ancestor_edges", recursive=True)
        )
        step = select(
            RoleInheritance.child_role_id,
            RoleInheritance.parent_role_id,
        ).join(base, RoleInheritance.child_role_id == base.c.parent_role_id)
        return base.union(step)

    async def ancestor_ids(
        self,
        role_ids: Sequence[int],
        *,
        max_depth: int,
    ) -> frozenset[int]:
        """展开给定角色的**全部祖先**（不含自身）。

        单条递归 CTE 取回闭包边，再在应用层按边做有深度上限的 BFS。

        为什么深度上限必须存在（`03 §4`"无限递归"）
        ------------------------------------------
        `UNION` 已经保证 SQL 层面不会无限递归，但它**只保证收敛**，
        不保证"结果有意义"：一条 A→B→C→A 的环会得到 {A,B,C} 这个
        看似正常的闭包。因此本方法用 `max_depth` 把"环导致的异常长链"
        显式暴露为错误（fail-closed），而不是静默接受一个可疑结果。
        """
        if not role_ids:
            return frozenset()

        edges = self._ancestor_edges_cte(role_ids)
        rows = (
            await self._session.execute(select(edges.c.child_role_id, edges.c.parent_role_id))
        ).all()

        parents: dict[int, set[int]] = {}
        for child_role_id, parent_role_id in rows:
            parents.setdefault(int(child_role_id), set()).add(int(parent_role_id))

        seen: set[int] = set()
        # frontier: 当前层节点 → 已走深度
        frontier: list[tuple[int, int]] = [(int(role_id), 0) for role_id in set(role_ids)]
        while frontier:
            current, depth = frontier.pop()
            if depth >= max_depth:
                # 还有下一层可走 → 说明链长超过上限（极可能是环）
                if parents.get(current):
                    raise RoleInheritanceDepthExceededError(
                        f"角色继承链深度超过上限 {max_depth}（起点 role_id={current}）"
                    )
                continue
            for parent in parents.get(current, ()):
                if parent in seen:
                    continue
                seen.add(parent)
                frontier.append((parent, depth + 1))
        # 自身不应出现在祖先集合中；若出现（自环/环路回到自身）则剔除，
        # 因为"自己是自己的祖先"没有业务含义，且会污染并集计算。
        return frozenset(seen - set(role_ids))

    async def expand_role_ids(self, role_ids: Sequence[int], *, max_depth: int) -> frozenset[int]:
        """给定角色集合 → **有效角色集合**（自身 ∪ 全部祖先）。"""
        base = frozenset(int(role_id) for role_id in role_ids)
        if not base:
            return frozenset()
        return base | await self.ancestor_ids(role_ids, max_depth=max_depth)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    async def add(self, *, parent_role_id: int, child_role_id: int) -> RoleInheritance:
        """建立继承关系。"""
        relation = RoleInheritance(parent_role_id=parent_role_id, child_role_id=child_role_id)
        self._session.add(relation)
        await self._session.flush()
        return relation

    async def remove(self, *, parent_role_id: int, child_role_id: int) -> bool:
        """解除继承关系；返回是否确实删除了行。"""
        # 用 RETURNING 判断"是否真的删掉了行"，而不是依赖 Result.rowcount：
        # rowcount 在抽象 Result 上并非有类型保证的接口（mypy --strict 会拒绝），
        # 而 RETURNING 的结果长度是确定的语义。
        deleted = (
            (
                await self._session.execute(
                    delete(RoleInheritance)
                    .where(
                        RoleInheritance.parent_role_id == parent_role_id,
                        RoleInheritance.child_role_id == child_role_id,
                    )
                    .returning(RoleInheritance.parent_role_id)
                )
            )
            .scalars()
            .all()
        )
        await self._session.flush()
        return len(deleted) > 0

    async def delete_all_for_role(self, role_id: int) -> frozenset[tuple[int, int]]:
        """删除与该角色相关的全部继承关系，返回被删除的 (parent, child) 集合。"""
        relations = await self.list_relations_for_role(role_id)
        removed = frozenset(
            (relation.parent_role_id, relation.child_role_id) for relation in relations
        )
        if removed:
            await self._session.execute(
                delete(RoleInheritance).where(
                    or_(
                        RoleInheritance.parent_role_id == role_id,
                        RoleInheritance.child_role_id == role_id,
                    )
                )
            )
            await self._session.flush()
        return removed

    # ------------------------------------------------------------------
    # 完整性检查（用于角色删除 / 用户角色校验）
    # ------------------------------------------------------------------
    async def count_direct_users(self, role_id: int) -> int:
        """直接持有该角色的未删除用户数量。"""
        stmt = select(func.count()).select_from(UserRole).where(UserRole.role_id == role_id)
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_active_role_ids(self, role_ids: Sequence[int]) -> frozenset[int]:
        """给定角色集合中**存在、未删除且 ACTIVE** 的角色 ID。

        有效权限计算只认 ACTIVE 角色（`03 §2` 的 status 语义）：
        被禁用的角色必须立即失去其权限。
        """
        if not role_ids:
            return frozenset()
        stmt = select(Role.id).where(
            Role.id.in_(sorted(set(role_ids))),
            Role.deleted_at.is_(None),
            Role.status == RoleStatus.ACTIVE,
        )
        return frozenset(int(x) for x in (await self._session.execute(stmt)).scalars().all())


class RoleInheritanceDepthExceededError(RuntimeError):
    """角色继承链深度超过上限（fail-closed）。

    单独一个异常类型而不是 ValueError：它是**数据完整性**问题
    （通常是库里出现了环），需要运维介入，调用方应当按 5xx 处理并告警，
    而不是当成"参数校验失败"返回 4xx。
    """


__all__ = [
    "GLOBAL_SCOPE",
    "PermissionResourceRepository",
    "PermissionVersionRepository",
    "RoleInheritanceDepthExceededError",
    "RoleInheritanceRepository",
    "RolePermissionRepository",
]
