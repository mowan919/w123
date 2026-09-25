"""字典端点（Phase 7 / Spec `05 §4` / `08 §9`）。

端点清单（与 Spec 逐条对应）
--------------------------
管理（admin 资源域，前缀 `/api/v1/admin`）：

| 方法 | 路径 | Spec |
|---|---|---|
| GET | `/dicts` | `05 §4` / `08 §9` |
| POST | `/dicts` | 同上 |
| GET | `/dicts/{id}` | 同上 |
| PUT | `/dicts/{id}` | 同上 |
| DELETE | `/dicts/{id}` | 同上 |
| GET | `/dicts/{id}/items` | 同上 |
| POST | `/dicts/{id}/items` | 同上 |
| PUT | `/dicts/{id}/items/{itemId}` | 同上 |
| DELETE | `/dicts/{id}/items/{itemId}` | 同上 |

公开查询（**不在** admin 域）：

| 方法 | 路径 | Spec |
|---|---|---|
| GET | `/api/v1/dicts/{dictCode}` | `05 §4` / `08 §9` |

关于公开查询的安全边界（**JUDGMENT-7-03**）
========================================
Spec 把本端点称为"公开查询"，且刻意**不放在** `/admin` 前缀下
（`05 §4` / `08 §9` 都写成 `/api/v1/dicts/{dictCode}`）。
但 Spec 没有任何一句说它**无需认证**。两种读法都自洽，取舍如下：

- **采用**：必须**已认证**（任意有效会话，不要求 `DICT_MANAGE`）。
- **不采用**：匿名可访问。

为什么不做成匿名端点：Spec 未授权匿名访问，而"把一个数据端点设为匿名"
是**安全面的扩张** —— 属于本项目禁止的自行放宽（`AGENTS.md §4`：
不得篡改或淡化需求）。反过来，"已认证即可读"不构成对需求的削弱：
`08 §10` 的"每个受保护 API 必须经过 API Permission 校验"针对的是
**admin 资源域**的 API（该条位于 `08` 的 Authorization 章节，
Base 见 `08 §1`；本端点按 `05 §4` 明确置于公开域），
因此这里的边界是"**必须已认证**"而不是"必须持有某个权限位"。

这个取舍的**改动面只有一处**（`get_current_actor` 依赖）：
若人类裁定"匿名可达"或"必须再挂一个权限位"，改的是这里的依赖，
不影响服务层与数据模型。

为什么读字典项没有独立详情端点
----------------------------
`05 §4` 的清单里没有 `GET /dicts/{id}/items/{itemId}`，
因此本项目不新增它（`AGENTS.md §4`：不得擅自扩范围）；
管理界面读某一项的完整信息走"读该字典的项列表"。

事务边界
-------
与既有端点同一约定：**端点负责 `commit()`**，Service 只 `flush()`
（`11 §3` 要求显式事务边界，也让 Service 可被组合进更大的事务）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.api.deps import CurrentActorDep, DbSessionDep, DictServiceDep
from app.core.response import success_response
from app.models.dict import SysDictItem, SysDictType
from app.schemas.dict import (
    DictItemCreateRequest,
    DictItemListQuery,
    DictItemListResponse,
    DictItemResponse,
    DictItemUpdateRequest,
    DictTypeCreateRequest,
    DictTypeDeleteResponse,
    DictTypeListQuery,
    DictTypePageResponse,
    DictTypeResponse,
    DictTypeUpdateRequest,
    PublicDictItemResponse,
    PublicDictResponse,
)
from app.services.dict import DeletedDictType, DictTypePage, PublicDict

#: 管理端点（挂载于 `/api/v1/admin`）。
router = APIRouter(tags=["Dictionary"])

#: 公开查询端点（挂载于 `/api/v1`，**不在** admin 域内）。理由见模块文档。
public_router = APIRouter(tags=["Dictionary"])


def _type_response(dict_type: SysDictType) -> DictTypeResponse:
    """把字典类型 ORM 对象映射为响应模型。"""
    return DictTypeResponse.model_validate(dict_type)


def _page_response(page: DictTypePage) -> DictTypePageResponse:
    """把分页结果映射为响应模型（`{list,total,pageNum,pageSize}`）。"""
    return DictTypePageResponse(
        list=[_type_response(item) for item in page.items],
        total=page.total,
        pageNum=page.page_num,
        pageSize=page.page_size,
    )


def _item_response(item: SysDictItem) -> DictItemResponse:
    """把字典项 ORM 对象映射为响应模型。"""
    return DictItemResponse.model_validate(item)


# ---------------------------------------------------------------------------
# 管理：字典类型
# ---------------------------------------------------------------------------
@router.get("/dicts", summary="字典类型列表")
async def list_dict_types(
    query: Annotated[DictTypeListQuery, Query()],
    actor: CurrentActorDep,
    service: DictServiceDep,
) -> JSONResponse:
    """分页列出字典类型（`05 §4`）。"""
    page = await service.list_types(
        actor=actor,
        keyword=query.keyword,
        status=query.status,
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(_page_response(page))


@router.post("/dicts", summary="创建字典类型")
async def create_dict_type(
    payload: DictTypeCreateRequest,
    actor: CurrentActorDep,
    service: DictServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """创建字典类型；编码重复返回 409（软删除后可重建同一编码）。"""
    dict_type = await service.create_type(
        actor=actor,
        dict_code=payload.dict_code,
        dict_name=payload.dict_name,
        description=payload.description,
        status=payload.status,
    )
    await session.commit()
    return success_response(_type_response(dict_type))


@router.get("/dicts/{dict_type_id}", summary="字典类型详情")
async def get_dict_type(
    dict_type_id: int,
    actor: CurrentActorDep,
    service: DictServiceDep,
) -> JSONResponse:
    """按 ID 读取字典类型。"""
    dict_type = await service.get_type(actor=actor, dict_type_id=dict_type_id)
    return success_response(_type_response(dict_type))


@router.put("/dicts/{dict_type_id}", summary="修改字典类型")
async def update_dict_type(
    dict_type_id: int,
    payload: DictTypeUpdateRequest,
    actor: CurrentActorDep,
    service: DictServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """修改名称 / 描述 / 状态。`dict_code` 不可修改（见 `DictService` 模块文档）。"""
    dict_type = await service.update_type(
        actor=actor,
        dict_type_id=dict_type_id,
        dict_name=payload.dict_name,
        description=payload.description,
        status=payload.status,
    )
    await session.commit()
    return success_response(_type_response(dict_type))


@router.delete("/dicts/{dict_type_id}", summary="删除字典类型（逻辑删除，级联其字典项）")
async def delete_dict_type(
    dict_type_id: int,
    actor: CurrentActorDep,
    service: DictServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """逻辑删除字典类型，并级联逻辑删除其下全部字典项。

    级联的理由见 `DictService` 的模块文档：编码唯一性是软删除感知的，
    因此删掉类型后可以用**同一编码**重建；若旧项留在库里，
    重建后的字典会立刻"长出"一批没人配置过的项。
    响应中的 `deleted_item_count` 如实回报级联清理的数量。
    """
    outcome: DeletedDictType = await service.delete_type(actor=actor, dict_type_id=dict_type_id)
    await session.commit()
    return success_response(
        DictTypeDeleteResponse(
            id=outcome.dict_type.id,
            dict_code=outcome.dict_type.dict_code,
            deleted_item_count=len(outcome.deleted_item_ids),
        )
    )


# ---------------------------------------------------------------------------
# 管理：字典项
# ---------------------------------------------------------------------------
@router.get("/dicts/{dict_type_id}/items", summary="字典项列表")
async def list_dict_items(
    dict_type_id: int,
    query: Annotated[DictItemListQuery, Query()],
    actor: CurrentActorDep,
    service: DictServiceDep,
) -> JSONResponse:
    """列出某字典的项（默认含已停用项，管理界面需要看到它们）。"""
    items = await service.list_items(actor=actor, dict_type_id=dict_type_id, status=query.status)
    return success_response(DictItemListResponse(items=[_item_response(item) for item in items]))


@router.post("/dicts/{dict_type_id}/items", summary="创建字典项")
async def create_dict_item(
    dict_type_id: int,
    payload: DictItemCreateRequest,
    actor: CurrentActorDep,
    service: DictServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """创建字典项；同字典下 `item_value` 重复返回 409。"""
    item = await service.create_item(
        actor=actor,
        dict_type_id=dict_type_id,
        item_label=payload.item_label,
        item_value=payload.item_value,
        item_code=payload.item_code,
        sort_order=payload.sort_order,
        status=payload.status,
        is_default=payload.is_default,
        description=payload.description,
    )
    await session.commit()
    return success_response(_item_response(item))


@router.put("/dicts/{dict_type_id}/items/{item_id}", summary="修改字典项")
async def update_dict_item(
    dict_type_id: int,
    item_id: int,
    payload: DictItemUpdateRequest,
    actor: CurrentActorDep,
    service: DictServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """修改字典项。

    路径同时给出字典 ID 与项 ID，服务层会校验**归属**：
    用 A 字典的路径改 B 字典的项会被拒绝（否则审计里的
    `dict_type_id` 与实际被改对象不一致，属审计失真）。
    """
    item = await service.update_item(
        actor=actor,
        dict_type_id=dict_type_id,
        item_id=item_id,
        item_label=payload.item_label,
        item_value=payload.item_value,
        item_code=payload.item_code,
        sort_order=payload.sort_order,
        status=payload.status,
        is_default=payload.is_default,
        description=payload.description,
    )
    await session.commit()
    return success_response(_item_response(item))


@router.delete("/dicts/{dict_type_id}/items/{item_id}", summary="删除字典项（逻辑删除）")
async def delete_dict_item(
    dict_type_id: int,
    item_id: int,
    actor: CurrentActorDep,
    service: DictServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """逻辑删除字典项（响应返回其删除后的状态：`status = DISABLED`）。

    响应**不含** `deleted_at`：与既有资源响应一致（`RoleResponse` 同样不下发
    逻辑删除列），删除时间可从审计中检索。
    """
    item = await service.delete_item(actor=actor, dict_type_id=dict_type_id, item_id=item_id)
    await session.commit()
    return success_response(_item_response(item))


# ---------------------------------------------------------------------------
# 公开查询（`05 §4`）
# ---------------------------------------------------------------------------
@public_router.get("/dicts/{dict_code}", summary="公开字典查询（按编码）")
async def get_public_dict(
    dict_code: str,
    actor: CurrentActorDep,
    service: DictServiceDep,
) -> JSONResponse:
    """按编码返回字典与**仅 ACTIVE** 的项。

    `actor` 依赖只用于**强制认证**（安全边界见模块文档的 JUDGMENT-7-03），
    本端点不使用操作者身份，也不记录审计：它是每个登录用户每次加载页面
    都会调用的读操作，逐次审计会把审计表变成访问日志，并稀释
    FAILURE 信号；管理侧的读（`/admin/dicts*`）仍然逐次审计。

    `DISABLED` 的字典与已删除的字典都返回 404 —— 不区分两者，
    避免把"停用"变成可探测信号。
    """
    outcome: PublicDict = await service.get_public(dict_code=dict_code)
    return success_response(
        PublicDictResponse(
            dict_code=outcome.dict_type.dict_code,
            dict_name=outcome.dict_type.dict_name,
            description=outcome.dict_type.description,
            items=[
                PublicDictItemResponse(
                    item_label=item.item_label,
                    item_value=item.item_value,
                    item_code=item.item_code,
                    sort_order=item.sort_order,
                    is_default=item.is_default,
                    description=item.description,
                )
                for item in outcome.items
            ],
        )
    )


__all__ = ["public_router", "router"]
