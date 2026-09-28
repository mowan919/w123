"""用户数据访问。

设计要点
-------
1. **范围下推到 SQL**（Spec 10 §10）：`list_in_scope` / `count_in_scope`
   均带 scope 条件，绝不在 Python 内存过滤。
2. 部门筛选与数据范围是**交集**关系：
   调用方传入范围外的部门集合时结果必然为空，而不是绕过范围。
   筛选接收的是**已展开的部门集合**（服务层负责把"含下级"展开），
   空集合翻译为 `false()` 而非"不加条件"。
3. 所有查询默认排除逻辑删除（Spec `02 §5`：删除后普通查询不得返回）。
4. 密码历史（Spec 00 §2 "最近 5 个密码不可重复"）只存哈希，并保持最多 5 条。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ColumnElement, delete, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import ResolvedScope
from app.db.base import utc_now
from app.models.enums import UserStatus
from app.models.password_history import AdminUserPasswordHistory
from app.models.user import AdminUser
from app.repositories.scope_filters import user_scope_condition


class UserRepository:
    """用户仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 单条读取
    # ------------------------------------------------------------------
    async def get(self, user_id: int, *, include_deleted: bool = False) -> AdminUser | None:
        """按 ID 读取用户；默认排除逻辑删除。"""
        stmt = select(AdminUser).where(AdminUser.id == user_id)
        if not include_deleted:
            stmt = stmt.where(AdminUser.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_username(self, username: str) -> AdminUser | None:
        """按登录名读取**未删除**用户（唯一性预校验）。"""
        stmt = select(AdminUser).where(
            AdminUser.username == username,
            AdminUser.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, user: AdminUser) -> AdminUser:
        """新增用户并 flush。"""
        self._session.add(user)
        await self._session.flush()
        return user

    # ------------------------------------------------------------------
    # 列表（范围 + 过滤 + 分页）
    # ------------------------------------------------------------------
    def _scoped_conditions(
        self,
        scope: ResolvedScope,
        *,
        department_ids: frozenset[int] | None,
        status: UserStatus | None,
        keyword: str | None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> list[ColumnElement[bool]]:
        """构造列表 / 计数的条件（唯一构造点）。

        `department_ids` 是**已经展开好**的部门集合，不是单个 ID：
        "本部门及下级"必须在服务层先用递归 CTE 展开成集合，
        仓储层只负责"把人筛到这个集合里"。这样仓储不认识
        `include_sub_departments` 这个界面概念，也就不可能
        在别处被误用成"传了个部门就自动含下级"。

        `department_ids` 为空集合时**显式返回 `false()`**，
        绝不能退化成"不加条件"：空集合来自"所选部门不存在 / 无子部门"，
        语义是"查不到人"；而"不加条件"是"看见所有人"。
        这个方向搞反就是权限放大（与 `scope_filters` 的 fail-closed 同一条理由）。

        `created_from` / `created_to` 落在 `AdminUser.created_at` 上，两端**含**边界。
        它们与数据范围是**与**的关系（同 `department_ids`），
        因此"按时间筛"永远筛不出范围外的人。
        """
        conditions: list[ColumnElement[bool]] = [
            AdminUser.deleted_at.is_(None),
            user_scope_condition(scope),
        ]
        if department_ids is not None:
            if not department_ids:
                conditions.append(false())
            else:
                # 与范围取交集：范围外的部门集合会自然得到空结果
                conditions.append(AdminUser.department_id.in_(sorted(department_ids)))
        if status is not None:
            conditions.append(AdminUser.status == status)
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(
                or_(AdminUser.username.ilike(pattern), AdminUser.display_name.ilike(pattern))
            )
        if created_from is not None:
            conditions.append(AdminUser.created_at >= created_from)
        if created_to is not None:
            conditions.append(AdminUser.created_at <= created_to)
        return conditions

    async def list_in_scope(
        self,
        scope: ResolvedScope,
        *,
        page_num: int,
        page_size: int,
        department_ids: frozenset[int] | None = None,
        status: UserStatus | None = None,
        keyword: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> list[AdminUser]:
        """分页列出范围内用户（`pageNum` 从 1 开始）。"""
        conditions = self._scoped_conditions(
            scope,
            department_ids=department_ids,
            status=status,
            keyword=keyword,
            created_from=created_from,
            created_to=created_to,
        )
        stmt = (
            select(AdminUser)
            .where(*conditions)
            .order_by(AdminUser.id.desc())
            .offset((page_num - 1) * page_size)
            .limit(page_size)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_in_scope(
        self,
        scope: ResolvedScope,
        *,
        department_ids: frozenset[int] | None = None,
        status: UserStatus | None = None,
        keyword: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> int:
        """统计范围内用户总数（与列表使用完全相同的条件）。"""
        conditions = self._scoped_conditions(
            scope,
            department_ids=department_ids,
            status=status,
            keyword=keyword,
            created_from=created_from,
            created_to=created_to,
        )
        stmt = select(func.count()).select_from(AdminUser).where(*conditions)
        return int((await self._session.execute(stmt)).scalar_one())

    async def count_super_admins(self) -> int:
        """统计未删除的 SUPER_ADMIN 用户数。

        用于阻止"禁用最后一个 SUPER_ADMIN"这类会导致系统不可管理的操作。
        """
        from app.models.role import Role, UserRole

        stmt = (
            select(func.count(func.distinct(AdminUser.id)))
            .select_from(AdminUser)
            .join(UserRole, UserRole.user_id == AdminUser.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                AdminUser.deleted_at.is_(None),
                Role.deleted_at.is_(None),
                Role.role_code == "SUPER_ADMIN",
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------
    # 密码历史
    # ------------------------------------------------------------------
    async def append_password_history(self, user_id: int, password_hash: str) -> None:
        """追加一条历史密码哈希。"""
        self._session.add(
            AdminUserPasswordHistory(
                user_id=user_id,
                password_hash=password_hash,
                created_at=utc_now(),
            )
        )
        await self._session.flush()

    async def list_password_hashes(self, user_id: int, *, limit: int) -> list[str]:
        """返回最近 `limit` 条历史密码哈希（由新到旧）。"""
        stmt = (
            select(AdminUserPasswordHistory.password_hash)
            .where(AdminUserPasswordHistory.user_id == user_id)
            .order_by(AdminUserPasswordHistory.id.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def prune_password_history(self, user_id: int, *, keep: int) -> int:
        """裁剪历史，只保留最近 `keep` 条。返回删除行数。

        使用 `RETURNING id` 统计删除行数，而不是 `CursorResult.rowcount`：
        后者在类型上只存在于 `CursorResult`（`AsyncSession.execute` 声明返回
        基类 `Result`），要读取它就必须引入 `Any` / `cast` 兜底。
        `RETURNING` 让删除结果自身携带类型信息，既精确又无需任何忽略注释。
        """
        newest = (
            select(AdminUserPasswordHistory.id)
            .where(AdminUserPasswordHistory.user_id == user_id)
            .order_by(AdminUserPasswordHistory.id.desc())
            .limit(keep)
            .scalar_subquery()
        )
        stmt = (
            delete(AdminUserPasswordHistory)
            .where(
                AdminUserPasswordHistory.user_id == user_id,
                AdminUserPasswordHistory.id.not_in(newest),
            )
            .returning(AdminUserPasswordHistory.id)
        )
        removed = (await self._session.execute(stmt)).scalars().all()
        return len(removed)


__all__ = ["UserRepository"]
