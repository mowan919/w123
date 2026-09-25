"""字典服务（Phase 7：字典类型与字典项的 CRUD / 唯一规则 / 软删除 / 公开查询）。

Frozen / 已裁定依据
------------------
- Spec `05 §1`~`§3`：模型、字段、以及**"同一 dict type 下 item_value
  必须支持软删除感知的唯一性"**。
- Spec `05 §4` / `08 §9`：管理端点与公开查询端点清单。
- Spec `05 §5`：System Parameter 与 Dictionary **必须分离**
  （因此本服务不提供任何"通用配置读取"能力）。
- Spec `00 §6` / `07 §3`：默认逻辑删除，绝不物理删除。
- Spec `08 §10` / `10 §2`：受保护 API 必须经过后端 API Permission 校验。
- Spec `10 §3`：授权判断集中在 `AuthorizationService`，
  业务 Service 中不出现 `if actor.is_super_admin` 分支。
- Spec `11 §3`：并发保护重点含"字典唯一值" → 唯一性同时由
  **数据库 partial unique index** 与**服务层预校验**表达。

三个需要解释的取舍
----------------
1. **`dict_code` 不可修改**（`PUT` 只接受 `dict_name` / `description` / `status`）。
   编码是字典**对外的稳定标识**：公开查询按它取字典
   （`GET /dicts/{dictCode}`），前端与调用方按它引用。
   允许改码会引入"配置还在、调用方却再也取不到"这类跨模块后果 ——
   与 `RoleService` 对 `role_code` 的处理同口径。需要换码时应新建字典并迁移。

2. **删除字典类型会级联逻辑删除其字典项**（而不是 409 拒绝）。
   规则沿用 `RoleService` 已确立的"**他人的依赖 → 拒绝；自己的从属 → 清理**"：
   字典项是字典类型**自己的从属数据**，不构成其他实体的依赖。
   更关键的是**不清理会产生静默的旧数据复活路径**：类型的唯一性约束是
   软删除感知的，因此删掉类型后可以用**同一 `dict_code`** 重建；
   若旧项仍在库里，重建后的字典会立刻"长出"一批谁也没配置过的项。
   删除的项 ID 与数量写入审计 `after_data`，使"静默"只体现在用户体验上，
   而不是体现在可追溯性上。

3. **公开查询不写审计、也不检查数据范围**（见 `get_public`）。理由在方法的
   docstring 里逐条给出；登记为 INTERIM-7-05。

`dict_code` / `item_value` 的并发（Spec `11 §3`）
-----------------------------------------------
服务层预校验给出**友好错误**（409 + 明确文案），数据库 partial unique index
给出**最终保证**（并发下两个请求同时通过预校验时，第二个会在 flush 时失败）。
两者都必须存在：只有预校验会漏并发，只有索引则错误信息无法解释。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import AuditAction, AuditRecorder, NullAuditRecorder
from app.auth.actor import CurrentActor
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.db.base import utc_now
from app.models.dict import (
    DESCRIPTION_LENGTH,
    DICT_CODE_LENGTH,
    DICT_NAME_LENGTH,
    ITEM_CODE_LENGTH,
    ITEM_LABEL_LENGTH,
    ITEM_VALUE_LENGTH,
    SysDictItem,
    SysDictType,
)
from app.models.enums import DictStatus
from app.repositories.dict import DictItemRepository, DictTypeRepository
from app.services.audit_guard import AuditGuard
from app.services.authorization import AuthorizationService

#: 审计资源类型。
RESOURCE_TYPE_DICT_TYPE = "DICT_TYPE"
RESOURCE_TYPE_DICT_ITEM = "DICT_ITEM"

#: 分页上界（与 `SessionListQuery` / `RoleListQuery` 一致）。
MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class DictTypePage:
    """字典类型分页结果（分页协议沿用人类已裁定的 `pageNum` / `pageSize`）。"""

    items: list[SysDictType]
    total: int
    page_num: int
    page_size: int


@dataclass(frozen=True, slots=True)
class DeletedDictType:
    """字典类型删除结果。

    `deleted_item_ids` 如实列出被**级联逻辑删除**的字典项，
    使响应与审计都能回答"这次删除顺带清掉了什么"。
    """

    dict_type: SysDictType
    deleted_item_ids: list[int]


@dataclass(frozen=True, slots=True)
class PublicDict:
    """公开查询结果：字典元数据 + **仅 ACTIVE** 的项。"""

    dict_type: SysDictType
    items: list[SysDictItem]


def _type_snapshot(dict_type: SysDictType) -> dict[str, Any]:
    """字典类型的审计快照（不含任何敏感字段）。"""
    return {
        "id": dict_type.id,
        "dict_code": dict_type.dict_code,
        "dict_name": dict_type.dict_name,
        "description": dict_type.description,
        "status": dict_type.status.value if dict_type.status is not None else None,
        "deleted_at": dict_type.deleted_at.isoformat() if dict_type.deleted_at else None,
    }


def _item_snapshot(item: SysDictItem) -> dict[str, Any]:
    """字典项的审计快照。

    字典项的值/编码**不是**敏感信息：它们本来就通过公开查询下发
    （见 `get_public`），因此这里记录完整字段以便取证
    （"这个下拉框什么时候多了个选项"必须能回答）。
    与之相对，系统参数的审计**不记录值**，理由见
    `app/services/system_param.py`。
    """
    return {
        "id": item.id,
        "dict_type_id": item.dict_type_id,
        "item_label": item.item_label,
        "item_value": item.item_value,
        "item_code": item.item_code,
        "sort_order": item.sort_order,
        "status": item.status.value if item.status is not None else None,
        "is_default": item.is_default,
        "description": item.description,
        "deleted_at": item.deleted_at.isoformat() if item.deleted_at else None,
    }


class DictService:
    """字典业务服务（类型 + 项）。"""

    def __init__(self, session: AsyncSession, *, audit: AuditRecorder | None = None) -> None:
        self._session = session
        self._types = DictTypeRepository(session)
        self._items = DictItemRepository(session)
        self._authz = AuthorizationService(session)
        recorder = audit or NullAuditRecorder()
        # 两个资源类型各持一个守卫：审计里的 resource_type 必须能区分
        # "改的是字典类型"还是"改的是字典项"，否则检索只能靠猜。
        self._type_guard = AuditGuard(recorder, RESOURCE_TYPE_DICT_TYPE)
        self._item_guard = AuditGuard(recorder, RESOURCE_TYPE_DICT_ITEM)

    # ------------------------------------------------------------------
    # 内部：目标加载与授权
    # ------------------------------------------------------------------
    async def _assert_can_manage(self, *, actor: CurrentActor, action: AuditAction) -> None:
        """字典管理权限的唯一入口（拒绝留痕）。"""
        with self._type_guard.denial_audited(actor=actor, action=action, resource_id=None):
            await self._authz.assert_can_manage_dicts(actor=actor)

    async def _load_type(
        self,
        *,
        actor: CurrentActor,
        dict_type_id: int,
        action: AuditAction,
        guard: AuditGuard | None = None,
    ) -> SysDictType:
        """**字典类型目标**的唯一入口：授权校验 + 读取。

        `guard` 允许调用方指定用哪个守卫记录拒绝：
        字典项的写操作也要先确认"类型存在"，而那些动作的
        `resource_type` 应当是 `DICT_ITEM` —— 否则审计里会出现
        "动作是 DICT_ITEM_CREATE、资源类型却是 DICT_TYPE"的错位记录，
        检索时会漏掉它。
        """
        active_guard = guard or self._type_guard
        with active_guard.denial_audited(actor=actor, action=action, resource_id=dict_type_id):
            await self._authz.assert_can_manage_dicts(actor=actor)

        dict_type = await self._types.get(dict_type_id)
        if dict_type is None:
            raise NotFoundError("字典类型不存在")
        return dict_type

    async def _load_item(
        self, *, actor: CurrentActor, dict_type_id: int, item_id: int, action: AuditAction
    ) -> SysDictItem:
        """**字典项目标**的唯一入口：授权 + 归属校验 + 读取。

        归属校验不是多余的：路径里同时出现 `{id}` 与 `{itemId}`
        （`05 §4`），若不校验归属，就可以用"A 字典的路径"去改 B 字典的项，
        使审计中的 `dict_type_id` 与实际被改对象不一致 —— 那是**审计失真**，
        比越权更难发现。
        """
        with self._item_guard.denial_audited(actor=actor, action=action, resource_id=item_id):
            await self._authz.assert_can_manage_dicts(actor=actor)

        item = await self._items.get(item_id)
        if item is None or item.dict_type_id != dict_type_id:
            raise NotFoundError("字典项不存在")
        return item

    # ------------------------------------------------------------------
    # 内部：字段校验
    # ------------------------------------------------------------------
    @staticmethod
    def _assert_text_lengths(
        *,
        dict_code: str | None = None,
        dict_name: str | None = None,
        description: str | None = None,
        item_label: str | None = None,
        item_value: str | None = None,
        item_code: str | None = None,
    ) -> None:
        """字段长度与非空校验（把数据库错误提前为 400）。"""
        checks = (
            (dict_code, DICT_CODE_LENGTH, "dict_code"),
            (dict_name, DICT_NAME_LENGTH, "dict_name"),
            (item_label, ITEM_LABEL_LENGTH, "item_label"),
            (item_value, ITEM_VALUE_LENGTH, "item_value"),
            (item_code, ITEM_CODE_LENGTH, "item_code"),
            (description, DESCRIPTION_LENGTH, "description"),
        )
        for value, limit, field in checks:
            if value is None:
                continue
            if not value.strip():
                raise BadRequestError(f"{field} 不能为空")
            if len(value) > limit:
                raise BadRequestError(f"{field} 长度不得超过 {limit}")

    async def _assert_value_available(
        self, *, dict_type_id: int, item_value: str, exclude_item_id: int | None = None
    ) -> None:
        """`05 §3`：同字典内 `item_value` 唯一（软删除感知）。"""
        existing = await self._items.get_by_value(dict_type_id, item_value)
        if existing is not None and existing.id != exclude_item_id:
            raise ConflictError(f"该字典下 item_value 已存在：{item_value}")

    async def _apply_default(
        self, *, dict_type_id: int, keep_item_id: int | None, is_default: bool
    ) -> None:
        """设置默认项：同字典其他项的 `is_default` 先被清掉。

        顺序很重要 —— 必须在本次写入 **之前** 清，否则数据库的
        partial unique index 会直接拒绝（同一字典存在两个默认项）。

        `keep_item_id` 在**新建**时为 `None`（新行还没有主键），
        在**修改**时传入被改项的 ID（它自己不能被清掉）。
        """
        if is_default:
            await self._items.clear_default(dict_type_id=dict_type_id, keep_item_id=keep_item_id)

    # ------------------------------------------------------------------
    # 字典类型：查询
    # ------------------------------------------------------------------
    async def get_type(self, *, actor: CurrentActor, dict_type_id: int) -> SysDictType:
        """按 ID 读取字典类型（授权拒绝留痕）。"""
        return await self._load_type(
            actor=actor, dict_type_id=dict_type_id, action=AuditAction.DICT_TYPE_READ
        )

    async def list_types(
        self,
        *,
        actor: CurrentActor,
        keyword: str | None = None,
        status: DictStatus | None = None,
        page_num: int = 1,
        page_size: int = 20,
    ) -> DictTypePage:
        """分页列出字典类型。

        读操作同样受 `DICT_MANAGE` 约束：字典清单是**配置面**
        （系统有哪些枚举），与 `ROLE_READ` 同口径。
        """
        if page_num < 1:
            raise BadRequestError("pageNum 必须大于等于 1")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise BadRequestError(f"pageSize 必须在 1..{MAX_PAGE_SIZE} 之间")

        await self._assert_can_manage(actor=actor, action=AuditAction.DICT_TYPE_READ)

        items = await self._types.list_types(
            keyword=keyword, status=status, page_num=page_num, page_size=page_size
        )
        total = await self._types.count_types(keyword=keyword, status=status)
        return DictTypePage(items=items, total=total, page_num=page_num, page_size=page_size)

    # ------------------------------------------------------------------
    # 字典类型：写入
    # ------------------------------------------------------------------
    async def create_type(
        self,
        *,
        actor: CurrentActor,
        dict_code: str,
        dict_name: str,
        description: str | None = None,
        status: DictStatus = DictStatus.ACTIVE,
    ) -> SysDictType:
        """创建字典类型。

        唯一性检查只针对**未删除**记录：`05 §3` 要求软删除感知的唯一性，
        `07 §3` 据此要求"逻辑删除后可用同一编码重建"。
        """
        self._assert_text_lengths(dict_code=dict_code, dict_name=dict_name, description=description)
        await self._assert_can_manage(actor=actor, action=AuditAction.DICT_TYPE_CREATE)

        if await self._types.get_by_code(dict_code) is not None:
            raise ConflictError(f"字典编码已存在：{dict_code}")

        dict_type = SysDictType(
            dict_code=dict_code,
            dict_name=dict_name,
            description=description,
            status=status,
        )
        await self._types.add(dict_type)

        self._type_guard.success(
            actor=actor,
            action=AuditAction.DICT_TYPE_CREATE,
            resource_id=dict_type.id,
            after=_type_snapshot(dict_type),
        )
        return dict_type

    async def update_type(
        self,
        *,
        actor: CurrentActor,
        dict_type_id: int,
        dict_name: str | None = None,
        description: str | None = None,
        status: DictStatus | None = None,
    ) -> SysDictType:
        """修改字典名称 / 描述 / 状态（`dict_code` 不可改，见模块说明）。"""
        dict_type = await self._load_type(
            actor=actor, dict_type_id=dict_type_id, action=AuditAction.DICT_TYPE_UPDATE
        )
        self._assert_text_lengths(dict_name=dict_name, description=description)

        before = _type_snapshot(dict_type)
        if dict_name is not None:
            dict_type.dict_name = dict_name
        if description is not None:
            dict_type.description = description
        if status is not None:
            dict_type.status = status
        await self._session.flush()

        self._type_guard.success(
            actor=actor,
            action=AuditAction.DICT_TYPE_UPDATE,
            resource_id=dict_type.id,
            before=before,
            after=_type_snapshot(dict_type),
        )
        return dict_type

    async def delete_type(self, *, actor: CurrentActor, dict_type_id: int) -> DeletedDictType:
        """逻辑删除字典类型，并**级联逻辑删除**其字典项（理由见模块说明）。

        绝不物理删除（AGENTS.md §7 / Spec `00 §6`）。
        """
        dict_type = await self._load_type(
            actor=actor, dict_type_id=dict_type_id, action=AuditAction.DICT_TYPE_DELETE
        )

        before = _type_snapshot(dict_type)
        # 级联逻辑删除字典项，返回被删除的 ORM 对象：一次遍历同时得到
        # "要写进审计的 ID 列表"与"会话内已呈现删除态的对象"。
        cascade = await self._items.soft_delete_items(dict_type_id=dict_type.id)
        item_ids = [item.id for item in cascade]

        dict_type.status = DictStatus.DISABLED
        dict_type.deleted_at = utc_now()
        await self._session.flush()

        self._type_guard.success(
            actor=actor,
            action=AuditAction.DICT_TYPE_DELETE,
            resource_id=dict_type.id,
            before=before,
            after={
                **_type_snapshot(dict_type),
                "deleted_item_ids": item_ids,
                "deleted_item_count": len(item_ids),
            },
        )
        return DeletedDictType(dict_type=dict_type, deleted_item_ids=item_ids)

    # ------------------------------------------------------------------
    # 字典项：查询
    # ------------------------------------------------------------------
    async def list_items(
        self,
        *,
        actor: CurrentActor,
        dict_type_id: int,
        status: DictStatus | None = None,
    ) -> list[SysDictItem]:
        """列出某字典的全部未删除项（含 DISABLED 项）。

        不做分页：`05 §4` 的端点清单没有为字典项定义分页参数，
        而一个枚举字典的项数在业务上有界（`05 §3` 的唯一性约束
        本身就限制了它的规模）。刻意**不**为它发明一套分页协议。

        默认**不筛状态**：管理界面必须能看到被停用的项，
        否则"这个项为什么不见了"无法排查。需要只看生效项时用
        `?status=ACTIVE`（公开查询则强制只下发 ACTIVE，见 `get_public`）。
        """
        # 先确认类型存在再列项：否则"类型不存在"会静默退化成空列表，
        # 调用方无从区分"没有项"与"类型 ID 写错了"。
        await self._load_type(
            actor=actor,
            dict_type_id=dict_type_id,
            action=AuditAction.DICT_ITEM_READ,
            guard=self._item_guard,
        )
        return await self._items.list_items(dict_type_id=dict_type_id, status=status)

    # ------------------------------------------------------------------
    # 字典项：写入
    # ------------------------------------------------------------------
    async def create_item(
        self,
        *,
        actor: CurrentActor,
        dict_type_id: int,
        item_label: str,
        item_value: str,
        item_code: str,
        sort_order: int = 0,
        status: DictStatus = DictStatus.ACTIVE,
        is_default: bool = False,
        description: str | None = None,
    ) -> SysDictItem:
        """在指定字典下创建项（`item_value` 同字典内唯一）。"""
        dict_type = await self._load_type(
            actor=actor,
            dict_type_id=dict_type_id,
            action=AuditAction.DICT_ITEM_CREATE,
            guard=self._item_guard,
        )
        self._assert_text_lengths(
            item_label=item_label,
            item_value=item_value,
            item_code=item_code,
            description=description,
        )
        await self._assert_value_available(dict_type_id=dict_type.id, item_value=item_value)

        # 必须在插入**之前**清掉同字典的其它默认项：
        # `DictItemRepository.add` 会 flush，若新行已带 `is_default=True`
        # 而旧默认项还在，partial unique index 会当场拒绝 ——
        # 那是"后者胜"这条规则被实现成 500 级约束冲突的经典顺序错误。
        await self._apply_default(
            dict_type_id=dict_type.id, keep_item_id=None, is_default=is_default
        )

        item = SysDictItem(
            dict_type_id=dict_type.id,
            item_label=item_label,
            item_value=item_value,
            item_code=item_code,
            sort_order=sort_order,
            status=status,
            is_default=is_default,
            description=description,
        )
        await self._items.add(item)

        self._item_guard.success(
            actor=actor,
            action=AuditAction.DICT_ITEM_CREATE,
            resource_id=item.id,
            after={**_item_snapshot(item), "dict_code": dict_type.dict_code},
        )
        return item

    async def update_item(
        self,
        *,
        actor: CurrentActor,
        dict_type_id: int,
        item_id: int,
        item_label: str | None = None,
        item_value: str | None = None,
        item_code: str | None = None,
        sort_order: int | None = None,
        status: DictStatus | None = None,
        is_default: bool | None = None,
        description: str | None = None,
    ) -> SysDictItem:
        """修改字典项。

        `item_value` **可以修改**（与 `dict_code` / `role_code` 不同）：
        它是"存进业务数据的值"，而当前版本里没有任何其它表或代码
        按字典取值做引用（字典是 Phase 7 才引入的），因此不存在
        "改值导致引用失效"的现实路径；一旦将来出现按值引用，
        这里需要重新评估（已登记在 §14 的观察项中）。
        修改时重新校验同字典唯一性。
        """
        item = await self._load_item(
            actor=actor,
            dict_type_id=dict_type_id,
            item_id=item_id,
            action=AuditAction.DICT_ITEM_UPDATE,
        )
        self._assert_text_lengths(
            item_label=item_label,
            item_value=item_value,
            item_code=item_code,
            description=description,
        )
        if item_value is not None:
            await self._assert_value_available(
                dict_type_id=item.dict_type_id,
                item_value=item_value,
                exclude_item_id=item.id,
            )

        before = _item_snapshot(item)
        # 默认项必须在**写入之前**清掉同字典其他项：partial unique index
        # 只允许一个 `is_default`，若先把自己更新为默认再清理，
        # flush 时会直接撞上约束（顺序错了就是 500 级错误）。
        if is_default:
            await self._apply_default(
                dict_type_id=item.dict_type_id, keep_item_id=item.id, is_default=is_default
            )
        if item_label is not None:
            item.item_label = item_label
        if item_value is not None:
            item.item_value = item_value
        if item_code is not None:
            item.item_code = item_code
        if sort_order is not None:
            item.sort_order = sort_order
        if status is not None:
            item.status = status
        if description is not None:
            item.description = description
        if is_default is not None:
            item.is_default = is_default
        await self._session.flush()

        self._item_guard.success(
            actor=actor,
            action=AuditAction.DICT_ITEM_UPDATE,
            resource_id=item.id,
            before=before,
            after=_item_snapshot(item),
        )
        return item

    async def delete_item(
        self, *, actor: CurrentActor, dict_type_id: int, item_id: int
    ) -> SysDictItem:
        """逻辑删除字典项（绝不物理删除）。

        删除默认项是允许的：字典可以暂时没有默认项，
        这比"禁止删除默认项、必须先把默认项挪走"更少意外
        （Spec 未规定该场景，登记为 INTERIM-7-07）。
        """
        item = await self._load_item(
            actor=actor,
            dict_type_id=dict_type_id,
            item_id=item_id,
            action=AuditAction.DICT_ITEM_DELETE,
        )

        before = _item_snapshot(item)
        item.status = DictStatus.DISABLED
        item.is_default = False
        item.deleted_at = utc_now()
        await self._session.flush()

        self._item_guard.success(
            actor=actor,
            action=AuditAction.DICT_ITEM_DELETE,
            resource_id=item.id,
            before=before,
            after=_item_snapshot(item),
        )
        return item

    # ------------------------------------------------------------------
    # 公开查询（`05 §4` / `08 §9`）
    # ------------------------------------------------------------------
    async def get_public(self, *, dict_code: str) -> PublicDict:
        """按 `dict_code` 返回字典与**仅 ACTIVE** 的项。

        为什么不接受 `actor`、不写审计、不检查数据范围
        --------------------------------------------
        1. **不检查数据范围**：字典是**全局配置**，不属于任何部门或用户，
           没有可限定的维度。给它套一个数据范围只会产生"某些人看不到
           某个枚举"的假问题（参考：角色清单也不套数据范围）。
        2. **不写审计**：`06 §1` 把审计定义为"高价值业务变更**与管理员行为**"。
           本端点是每个登录用户**每次加载页面**都会调用的读操作
           （前端靠它渲染下拉框），逐次写审计会把审计表变成访问日志，
           并稀释真正有价值的 FAILURE 信号。
           管理侧的读（`GET /admin/dicts*`）仍然逐次审计 —— 那才是
           "管理员行为"。两者口径不同是有意的（INTERIM-7-05）。
        3. **不存在"按列表枚举"的入口**：本端点必须给出具体的 `dict_code`，
           无法用它列出系统里有哪些字典，因此不构成配置面泄漏。

        `DISABLED` 的字典与已删除的字典一律返回 `NotFoundError`：
        不区分"不存在"与"已停用"，避免把停用状态变成可探测信号，
        而且调用方对两者的处理本来就相同（该字典不可用）。
        """
        dict_type = await self._types.get_by_code(dict_code)
        if dict_type is None or dict_type.status is not DictStatus.ACTIVE:
            raise NotFoundError("字典不存在或未启用")

        items = await self._items.list_items(dict_type_id=dict_type.id, status=DictStatus.ACTIVE)
        return PublicDict(dict_type=dict_type, items=items)


__all__ = [
    "MAX_PAGE_SIZE",
    "RESOURCE_TYPE_DICT_ITEM",
    "RESOURCE_TYPE_DICT_TYPE",
    "DeletedDictType",
    "DictService",
    "DictTypePage",
    "PublicDict",
]
