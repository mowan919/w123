"""V3.1 四新增域的**结构层**通用 CRUD 底座（VCTN §33）。

为什么需要这一层
--------------
V3.1 四域共约 44 张表，绝大多数是"配置 / 字典 / 流水"类实体，
其 CRUD 的数据层口径高度一致（软删除感知、分页、按索引列精确过滤、
服务端字段回填、权限门 + 审计）。逐一手写 44 套 bespoke 仓储 / 服务
既违背 DRY，也容易在"软删除过滤""分页全序"这些**易错点**上漂移。

本模块提供**通用**底座：
- `BaseCrudRepository`：只管数据访问（增 / 按 ID 取 / 分页列表 / 计数 /
  软删除），软删除感知、分页全序 `(created_at desc, id desc)` 在此一处实现。
- `BaseCrudService`：权限门（`ApiPermissionCode`）+ 服务端字段回填
  （`created_by*` / `updated_by`）+ 审计（拒绝由路由级 `require_api_permission`
  留痕，成功由本服务留痕）+ 标准 CRUD。

刻意**不**下沉业务规则
--------------------
等级计算 / 积分记账 / 工具执行 / 博客发布流等属 `docs/.../09` 未冻结项
（§09-D 明令禁止 Agent 自行发明）。因此本底座只交付"能存能取能改能删"
的结构能力；任何业务语义（状态机、额度、幂等）必须由后续冻结决策补充，
不得在本层臆造取值域或规则。

与既有 bespoke 仓储的关系
----------------------
既有域（`notification` / `user` / `role` …）保留其 hand-written 仓储，
因为它们的数据层有**专属硬规则**（如收件箱必须按 `user_id` 过滤、公告扇出）。
本通用底座只用于"没有专属硬规则"的 V3.1 结构层实体；若某实体后续被裁定
带有专属硬规则，应让它退回 bespoke 仓储，而不是把规则塞进通用底座。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditEvent, AuditRecorder, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import NotFoundError
from app.db.base import utc_now
from app.services.authorization import ApiPermissionCode, AuthorizationService

#: 服务端托管字段：永远不出现在请求契约里，由服务层从 `Actor` 回填。
_SERVER_MANAGED: frozenset[str] = frozenset(
    {
        "created_by",
        "created_by_username",
        "updated_by",
        "approved_by",
        "reviewed_by",
        "operator_id",
        "operator_username",
    }
)

#: 永不作为请求字段出现的列（主键 / 时间戳 / 逻辑删除）。
_NEVER_REQUEST: frozenset[str] = frozenset({"id", "created_at", "updated_at", "deleted_at"})


class BaseCrudRepository[T]:
    """V3.1 结构层实体的数据访问底座。

    仅做数据访问与"软删除感知 / 分页全序"这类跨实体一致的口径。
    """

    def __init__(self, session: AsyncSession, model_cls: type[T]) -> None:
        self._session = session
        self._model = model_cls

    # ------------------------------------------------------------------
    # 内部：软删除感知与排序
    # ------------------------------------------------------------------

    @property
    def _has_soft_delete(self) -> bool:
        return hasattr(self._model, "deleted_at")

    @property
    def _has_created_at(self) -> bool:
        return hasattr(self._model, "created_at")

    def _active(self, stmt: Select[tuple[T]]) -> Select[tuple[T]]:
        if self._has_soft_delete:
            return stmt.where(self._model.deleted_at.is_(None))  # type: ignore[attr-defined]
        return stmt

    def _ordered(self, stmt: Select[tuple[T]]) -> Select[tuple[T]]:
        if self._has_created_at:
            return stmt.order_by(
                self._model.created_at.desc(),  # type: ignore[attr-defined]
                self._model.id.desc(),  # type: ignore[attr-defined]
            )
        return stmt.order_by(self._model.id.desc())  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    async def add(self, instance: T) -> T:
        """写入并 flush（拿到数据库约束校验结果）。"""
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def flush(self) -> None:
        await self._session.flush()

    async def soft_delete(self, instance: T, *, now: datetime) -> None:
        """逻辑删除（无 `deleted_at` 的关联表退化为物理删除）。"""
        if not self._has_soft_delete:
            await self._session.delete(instance)
            await self._session.flush()
            return
        instance.deleted_at = now  # type: ignore[attr-defined]
        await self._session.flush()

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    async def get_by_id(self, entity_id: int, *, strict: bool = False) -> T | None:
        """按 ID 取未删除实体；`strict` 时不存在抛 `NotFoundError`。"""
        stmt = select(self._model).where(self._model.id == entity_id)  # type: ignore[attr-defined]
        instance = (await self._session.execute(self._active(stmt))).scalars().first()
        if instance is None and strict:
            raise NotFoundError("资源不存在")
        return instance

    async def list(
        self,
        *,
        filters: dict[str, Any] | None = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> list[T]:
        """分页列出未删除实体（新的在前）。

        `filters` 仅支持"等值精确过滤"（语义与索引列一致）；`None` 值忽略。
        """
        stmt = self._active(select(self._model))
        for name, value in (filters or {}).items():
            if value is None:
                continue
            stmt = stmt.where(getattr(self._model, name) == value)
        stmt = self._ordered(stmt).offset((page_num - 1) * page_size).limit(page_size)
        return list((await self._session.execute(stmt)).scalars().all())

    async def count(self, *, filters: dict[str, Any] | None = None) -> int:
        """统计未删除实体数（与 `list` 同口径，供分页总数）。"""
        stmt = select(func.count()).select_from(self._model)
        if self._has_soft_delete:
            stmt = stmt.where(self._model.deleted_at.is_(None))  # type: ignore[attr-defined]
        for name, value in (filters or {}).items():
            if value is None:
                continue
            stmt = stmt.where(getattr(self._model, name) == value)
        return int((await self._session.execute(stmt)).scalar_one())


@dataclass(frozen=True, slots=True)
class CrudPage:
    """结构层 CRUD 分页结果（分页协议沿用人类已裁定的 `pageNum` / `pageSize`）。"""

    items: list[Any]
    total: int
    page_num: int
    page_size: int


class BaseCrudService[T]:
    """V3.1 结构层实体的服务底座：权限门 + 服务端字段回填 + 审计 + 标准 CRUD。

    端点层负责"路由级 `require_api_permission`（拒绝留痕）"，本服务提供
    "纵深防御的服务级权限断言"与"成功审计"，两者动作名保持一致。
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: AuditRecorder | None = None,
        model_cls: type[T],
        permission_code: ApiPermissionCode,
        resource_type: str,
        audit_create: AuditAction,
        audit_update: AuditAction,
        audit_delete: AuditAction,
        audit_read: AuditAction,
    ) -> None:
        self._session = session
        self._repo = BaseCrudRepository(session, model_cls)
        self._model = model_cls
        self._audit = audit or NullAuditRecorder()
        self._permission_code = permission_code
        self._resource_type = resource_type
        self._audit_create = audit_create
        self._audit_update = audit_update
        self._audit_delete = audit_delete
        self._audit_read = audit_read

    # ------------------------------------------------------------------
    # 权限
    # ------------------------------------------------------------------

    async def assert_manage(self, actor: CurrentActor, *, read: bool = False) -> None:
        """纵深防御：服务级权限断言（路由级已先判过一次）。"""
        del read  # 结构层只有一个管理位，读与写共用；保留参数以便将来细分。
        await AuthorizationService(self._session).assert_api_permission(
            actor=actor, api_code=self._permission_code
        )

    # ------------------------------------------------------------------
    # 服务端字段回填
    # ------------------------------------------------------------------

    def _apply_server_fields(self, instance: T, actor: CurrentActor, *, creating: bool) -> None:
        cols = {c.name for c in self._model.__table__.columns}  # type: ignore[attr-defined]
        if creating:
            if "created_by" in cols:
                instance.created_by = actor.user_id  # type: ignore[attr-defined]
            if "created_by_username" in cols:
                instance.created_by_username = actor.username  # type: ignore[attr-defined]
        else:
            if "updated_by" in cols:
                instance.updated_by = actor.user_id  # type: ignore[attr-defined]

    @staticmethod
    def _server_managed() -> frozenset[str]:
        return _SERVER_MANAGED

    @staticmethod
    def _never_request() -> frozenset[str]:
        return _NEVER_REQUEST

    # ------------------------------------------------------------------
    # 标准 CRUD
    # ------------------------------------------------------------------

    async def create(self, actor: CurrentActor, *, fields: dict[str, Any]) -> T:
        """创建一条记录（服务端字段自动回填），并写成功审计。"""
        await self.assert_manage(actor)
        instance = self._model()
        for key, value in fields.items():
            setattr(instance, key, value)
        self._apply_server_fields(instance, actor, creating=True)
        await self._repo.add(instance)
        self._record(actor, self._audit_create, instance.id, after=fields)  # type: ignore[attr-defined]
        return instance

    async def get(self, actor: CurrentActor, *, entity_id: int) -> T:
        """取一条（含权限断言）。"""
        await self.assert_manage(actor, read=True)
        instance = await self._repo.get_by_id(entity_id, strict=True)
        assert instance is not None
        return instance

    async def list(
        self,
        actor: CurrentActor,
        *,
        filters: dict[str, Any] | None = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> CrudPage:
        """分页列表（含权限断言与总数）。"""
        await self.assert_manage(actor, read=True)
        self._validate_page(page_num, page_size)
        items = await self._repo.list(filters=filters, page_num=page_num, page_size=page_size)
        total = await self._repo.count(filters=filters)
        return CrudPage(items=items, total=total, page_num=page_num, page_size=page_size)

    async def update(self, actor: CurrentActor, *, entity_id: int, fields: dict[str, Any]) -> T:
        """局部更新（只改 `fields` 中出现的字段），并写成功审计。"""
        await self.assert_manage(actor)
        instance = await self._repo.get_by_id(entity_id, strict=True)
        assert instance is not None
        for key, value in fields.items():
            setattr(instance, key, value)
        self._apply_server_fields(instance, actor, creating=False)
        await self._repo.flush()
        self._record(actor, self._audit_update, entity_id, after=fields)
        return instance

    async def delete(self, actor: CurrentActor, *, entity_id: int) -> T:
        """逻辑删除（含权限断言与审计）。"""
        await self.assert_manage(actor)
        instance = await self._repo.get_by_id(entity_id, strict=True)
        assert instance is not None
        await self._repo.soft_delete(instance, now=utc_now())
        self._record(actor, self._audit_delete, entity_id)
        return instance

    # ------------------------------------------------------------------
    # 内部：审计
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_page(page_num: int, page_size: int) -> None:
        if page_num < 1:
            raise ValueError("pageNum 必须大于等于 1")
        if page_size < 1 or page_size > 100:
            raise ValueError("pageSize 必须在 1 到 100 之间")

    def _record(
        self,
        actor: CurrentActor,
        action: AuditAction,
        resource_id: int | None,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        self._audit.record(
            AuditEvent.build(
                action=action,
                resource_type=self._resource_type,
                resource_id=resource_id,
                operator_id=actor.user_id,
                operator_username=actor.username,
                before_data=before,
                after_data=after,
                ip=actor.ip,
                user_agent=actor.user_agent,
            )
        )


__all__ = ["BaseCrudRepository", "BaseCrudService", "CrudPage"]
