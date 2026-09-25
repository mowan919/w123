"""字典数据访问（Spec `05 §1`~`§3`）。

职责边界
-------
本模块只做数据访问：把"谁可以管理字典"（授权）与"字典项能不能删"（业务规则）
留给 `app.services.dict`。Repository **不接受** `CurrentActor`，
也不做任何授权判断（见 `app/repositories/__init__.py` 的分工说明）。

为什么类型与项分成两个 Repository 类
----------------------------------
两者是父子关系但不是同一个聚合：类型的引用检查（"下面还有没有项"）
与项的"同字典唯一"判定都需要**各自独立**的读写入口；
把它们塞进一个类会让"删类型时要级联处理项"这类跨实体操作
看起来像一个普通方法，而它其实是一条需要审计的业务规则。
"""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utc_now
from app.models.dict import SysDictItem, SysDictType
from app.models.enums import DictStatus

#: `_apply_filters` 的泛型参数：保证过滤后语句的行类型不丢失。
_RowT = TypeVar("_RowT", bound=tuple[Any, ...])


class DictTypeRepository:
    """字典类型仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, dict_type_id: int) -> SysDictType | None:
        """按 ID 读取**未删除**字典类型。"""
        stmt = select(SysDictType).where(
            SysDictType.id == dict_type_id,
            SysDictType.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def get_by_code(self, dict_code: str) -> SysDictType | None:
        """按编码读取**未删除**字典类型（唯一性预校验 + 公开查询）。"""
        stmt = select(SysDictType).where(
            SysDictType.dict_code == dict_code,
            SysDictType.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def add(self, dict_type: SysDictType) -> SysDictType:
        """新增字典类型并 flush（拿到数据库唯一约束的校验结果）。"""
        self._session.add(dict_type)
        await self._session.flush()
        return dict_type

    async def list_types(
        self,
        *,
        keyword: str | None = None,
        status: DictStatus | None = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> list[SysDictType]:
        """分页列出未删除字典类型（按 ID 升序，保证分页稳定）。"""
        stmt = (
            select(SysDictType)
            .where(SysDictType.deleted_at.is_(None))
            .order_by(SysDictType.id)
            .offset((page_num - 1) * page_size)
            .limit(page_size)
        )
        stmt = self._apply_filters(stmt, keyword=keyword, status=status)
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_types(
        self, *, keyword: str | None = None, status: DictStatus | None = None
    ) -> int:
        """统计未删除字典类型数量（与 `list_types` 同口径）。"""
        stmt = select(func.count()).select_from(SysDictType).where(SysDictType.deleted_at.is_(None))
        stmt = self._apply_filters(stmt, keyword=keyword, status=status)
        return int((await self._session.execute(stmt)).scalar_one())

    @staticmethod
    def _apply_filters(
        stmt: Select[_RowT], *, keyword: str | None, status: DictStatus | None
    ) -> Select[_RowT]:
        """附加可选过滤条件（list / count 共用，保证两者口径一致）。"""
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    SysDictType.dict_code.ilike(pattern),
                    SysDictType.dict_name.ilike(pattern),
                )
            )
        if status is not None:
            stmt = stmt.where(SysDictType.status == status)
        return stmt


class DictItemRepository:
    """字典项仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, item_id: int) -> SysDictItem | None:
        """按 ID 读取**未删除**字典项。"""
        stmt = select(SysDictItem).where(
            SysDictItem.id == item_id,
            SysDictItem.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def get_by_value(self, dict_type_id: int, item_value: str) -> SysDictItem | None:
        """按 (字典类型, 取值) 读取未删除字典项（`05 §3` 唯一性的预校验）。"""
        stmt = select(SysDictItem).where(
            SysDictItem.dict_type_id == dict_type_id,
            SysDictItem.item_value == item_value,
            SysDictItem.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def add(self, item: SysDictItem) -> SysDictItem:
        """新增字典项并 flush。"""
        self._session.add(item)
        await self._session.flush()
        return item

    async def list_items(
        self,
        *,
        dict_type_id: int,
        status: DictStatus | None = None,
    ) -> list[SysDictItem]:
        """列出某字典类型下的未删除项（按 `sort_order`, `id` 升序）。

        `sort_order` 相同时用 `id` 兜底排序：否则同一字典的项在不同查询里
        可能以不同顺序返回（PostgreSQL 不保证无序排序的稳定性），
        前端下拉框顺序会随机跳动。
        """
        stmt = (
            select(SysDictItem)
            .where(
                SysDictItem.dict_type_id == dict_type_id,
                SysDictItem.deleted_at.is_(None),
            )
            .order_by(SysDictItem.sort_order, SysDictItem.id)
        )
        if status is not None:
            stmt = stmt.where(SysDictItem.status == status)
        return list((await self._session.execute(stmt)).scalars().all())

    async def clear_default(self, *, dict_type_id: int, keep_item_id: int | None = None) -> None:
        """把该字典下其他项的 `is_default` 置为 false。

        "每个字典至多一个默认项"由数据库 partial unique index 兜底，
        但若只靠索引，正常调用会直接撞成 500 级约束冲突；
        因此服务层在设置默认项前先做这一步，让行为是"后者胜"（可预期）。

        ## 为什么用 ORM 变更而不是 Core `update()`

        1. **会话一致性**：Core `update()` 不维护身份映射。若用 `RETURNING`
           只取回主键，SQLAlchemy 只能识别"哪些行被命中"，却不一定把每个
           被改列的**新值**写回内存对象 —— 结果同一事务内
           `session.get()` 会返回 `is_default=True` 的幽灵对象，
           而库里那一行已经是 false。ORM 变更让内存与库只有一份真相。
        2. **顺序可控**：本方法**主动 `flush()`**。这一点是必需的 ——
           partial unique index 在任何时刻都只允许一个默认项，
           而"清旧默认"与"设新默认"是两次写入，必须严格分开提交。
           若攒到外层一次 flush，SQLAlchemy 的 UPDATE 顺序由主键决定，
           就可能先写"新默认"再清"旧默认"而撞上索引。

        字典项的规模有界（见 `DictService.list_items` 的说明：
        `05 §3` 的唯一性约束本身就限制了项数），因此按行加载的成本可接受。
        """
        now = utc_now()
        for item in await self.list_items(dict_type_id=dict_type_id):
            if not item.is_default or item.id == keep_item_id:
                continue
            item.is_default = False
            item.updated_at = now
        await self._session.flush()

    async def soft_delete_items(self, *, dict_type_id: int) -> list[SysDictItem]:
        """批量逻辑删除某字典下的全部未删除项，返回被删除的对象。

        返回 ORM 对象而不是计数：调用方（`DictService.delete_type`）
        需要把被级联删除的 ID 写进审计，而它同时也要保证这些对象在
        会话里立刻呈现"已删除"状态 —— 一次遍历同时满足两个需求。

        绝不物理删除（`AGENTS.md §7` / Spec `00 §6`）。

        顺带清掉 `is_default`：删除态的行不应继续占据
        `uq_sys_dict_item_type_default_active` 那个 partial unique index
        （该索引虽然是软删除感知的，但"删除后仍标记为默认"会让
        审计与人工排查都读到一个自相矛盾的状态）。
        """
        items = await self.list_items(dict_type_id=dict_type_id)
        now = utc_now()
        for item in items:
            item.deleted_at = now
            item.status = DictStatus.DISABLED
            item.is_default = False
            item.updated_at = now
        await self._session.flush()
        return items


__all__ = ["DictItemRepository", "DictTypeRepository"]
