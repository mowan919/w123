"""系统参数数据访问（Spec `05 §5`）。

职责边界
-------
只做数据访问与"未删除 / 唯一性"这类**数据层**口径；
"停用的参数读取方必须 fail-closed""值必须符合声明类型"这类规则
属业务规则，落在 `app/services/system_param.py`。

与字典仓储的关系
--------------
两者**没有任何共享代码**（`05 §5` 第一句要求 System Parameter
与 Dictionary 分离）。刻意不做"通用 KV 表"再让两者共用 ——
那正是 Spec 要求分离的东西。
"""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SystemParamStatus
from app.models.param import SysParam

#: `_apply_filters` 的泛型参数：保证过滤后语句的行类型不丢失。
_RowT = TypeVar("_RowT", bound=tuple[Any, ...])


class SystemParamRepository:
    """系统参数仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, param_id: int) -> SysParam | None:
        """按 ID 读取**未删除**参数。"""
        stmt = select(SysParam).where(
            SysParam.id == param_id,
            SysParam.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def get_by_key(self, param_key: str) -> SysParam | None:
        """按键读取**未删除**参数（唯一性预校验 + 读取方取值路径）。"""
        stmt = select(SysParam).where(
            SysParam.param_key == param_key,
            SysParam.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def add(self, param: SysParam) -> SysParam:
        """新增参数并 flush（拿到数据库唯一约束的校验结果）。"""
        self._session.add(param)
        await self._session.flush()
        return param

    async def list_params(
        self,
        *,
        keyword: str | None = None,
        status: SystemParamStatus | None = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> list[SysParam]:
        """分页列出未删除参数（按 ID 升序，保证分页稳定）。"""
        stmt = (
            select(SysParam)
            .where(SysParam.deleted_at.is_(None))
            .order_by(SysParam.id)
            .offset((page_num - 1) * page_size)
            .limit(page_size)
        )
        stmt = self._apply_filters(stmt, keyword=keyword, status=status)
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_params(
        self, *, keyword: str | None = None, status: SystemParamStatus | None = None
    ) -> int:
        """统计未删除参数数量（与 `list_params` 同口径）。"""
        stmt = select(func.count()).select_from(SysParam).where(SysParam.deleted_at.is_(None))
        stmt = self._apply_filters(stmt, keyword=keyword, status=status)
        return int((await self._session.execute(stmt)).scalar_one())

    @staticmethod
    def _apply_filters(
        stmt: Select[_RowT], *, keyword: str | None, status: SystemParamStatus | None
    ) -> Select[_RowT]:
        """附加可选过滤条件（list / count 共用，保证两者口径一致）。"""
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    SysParam.param_key.ilike(pattern),
                    SysParam.param_name.ilike(pattern),
                )
            )
        if status is not None:
            stmt = stmt.where(SysParam.status == status)
        return stmt


__all__ = ["SystemParamRepository"]
