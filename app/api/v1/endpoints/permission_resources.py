"""权限资源端点（Phase 8 / DD-20 §5.1.1 冻结契约）。

端点清单（**冻结**：`docs/DECISION-REQUEST-PHASE-3.md` §5.1.1，DD-20 方案 A 已批准）
------------------------------------------------------------------------------
| 方法 | 路径 |
|---|---|
| GET | `/permission-resources` |
| POST | `/permission-resources` |
| GET | `/permission-resources/tree` |
| GET | `/permission-resources/{id}` |
| PUT | `/permission-resources/{id}` |
| POST | `/permission-resources/{id}/delete` |
| GET | `/permission-resources/{id}/pages` |
| PUT | `/permission-resources/{id}/pages` |

这 8 条**不是**自造接口面：`08 §7` 只列了角色与角色授权的端点，
资源定义端点缺席，DD-20 把这份清单作为契约的一部分一并冻结，
并明确"资源 CRUD 的 HTTP 暴露属 `docs/verification/008` 的交付范围"
（见 `docs/DESIGN-DECISIONS.md` §2 DD-20 条）。本模块即该交付。

`/tree` 必须先于 `/{id}` 注册
---------------------------
FastAPI 按声明顺序匹配路径。若 `/{resource_id}` 先声明，
`GET /permission-resources/tree` 会被它捕获，
`"tree"` 交给 `int` 解析失败 → **422**，而不是"路由不存在"。
这类顺序错误在评审时几乎看不出来（两个装饰器都正确），
因此本文件把 `tree` 放在 `{id}` 之前，并在测试里**逐条钉住路径面**。

删除用 `POST .../delete` 而不是 `DELETE`
-------------------------------------
这是 `08 §7` 既有风格（`POST /roles/{id}/delete`）与本项目"业务数据一律
逻辑删除"（`00 §6`）的共同结果：HTTP `DELETE` 语义上暗示资源消失，
而这里发生的是**打标记**（`deleted_at` + `status = DISABLED`）。
沿用既有动作词保持一致，避免"有的地方 DELETE、有的地方 POST /delete"。

事务边界
-------
与既有端点同一约定：**端点负责 `commit()`**，Service 只 `flush()`。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.api.deps import (
    CurrentActorDep,
    DbSessionDep,
    PermissionResourceServiceDep,
    require_api_permission,
)
from app.audit import AuditAction
from app.core.errors import BadRequestError
from app.core.response import success_response
from app.models.permission import PermissionResource
from app.schemas.permission import (
    MenuPagesResponse,
    MenuPagesUpdateRequest,
    PermissionResourceCreateRequest,
    PermissionResourceListQuery,
    PermissionResourcePageResponse,
    PermissionResourceResponse,
    PermissionResourceTreeNodeResponse,
    PermissionResourceUpdateRequest,
)
from app.services.authorization import ApiPermissionCode
from app.services.permission_resource import (
    RESOURCE_TYPE,
    ResourcePage,
    ResourceTreeNode,
)

router = APIRouter(tags=["PermissionResource"])

#: 本模块所有端点共用的权限位（`08 §10` 后端强制授权）。
_MANAGE = ApiPermissionCode.PERMISSION_RESOURCE_MANAGE


def _manage_dependency(action: AuditAction) -> list[Any]:
    """构造路由级依赖：需要 `PERMISSION_RESOURCE_MANAGE`，拒绝写 FAILURE 审计。

    返回 `list[Any]` 而非更精确的类型：FastAPI 的依赖项是
    `Depends(...)` 的**运行时对象**，没有可供 `mypy --strict` 使用的公开类型
    （`Depends` 本身是个函数）。这里的宽松是刻意的，且被限制在装饰器参数这一处。
    """
    return [Depends(require_api_permission(_MANAGE, action=action, resource_type=RESOURCE_TYPE))]


def _resource_response(resource: PermissionResource) -> PermissionResourceResponse:
    """把资源 ORM 对象映射为响应模型。

    全部类型专属列都输出（不适用的为 `null`），而不是按类型裁剪字段集：
    前端渲染资源表单时需要知道"这个字段在这个类型下不适用"，
    返回结构随类型变化会让客户端的类型定义无法表达。
    """
    return PermissionResourceResponse(
        id=resource.id,
        resource_type=resource.resource_type,
        resource_code=resource.resource_code,
        resource_name=resource.resource_name,
        parent_id=resource.parent_id,
        sort_order=resource.sort_order,
        status=resource.status,
        route_path=resource.route_path,
        component_path=resource.component_path,
        icon=resource.icon,
        api_method=resource.api_method,
        api_path=resource.api_path,
        field_key=resource.field_key,
        owner_resource_id=resource.owner_resource_id,
        created_at=resource.created_at,
        updated_at=resource.updated_at,
    )


def _page_response(page: ResourcePage) -> PermissionResourcePageResponse:
    """把分页结果映射为响应模型（`{list,total,pageNum,pageSize}`）。"""
    return PermissionResourcePageResponse(
        list=[_resource_response(item) for item in page.items],
        total=page.total,
        pageNum=page.page_num,
        pageSize=page.page_size,
    )


def _tree_response(node: ResourceTreeNode) -> PermissionResourceTreeNodeResponse:
    """递归映射资源树节点。"""
    return PermissionResourceTreeNodeResponse(
        resource=_resource_response(node.resource),
        children=[_tree_response(child) for child in node.children],
    )


@router.get(
    "/permission-resources",
    summary="权限资源列表",
    dependencies=_manage_dependency(AuditAction.PERMISSION_RESOURCE_READ),
)
async def list_permission_resources(
    query: Annotated[PermissionResourceListQuery, Query()],
    actor: CurrentActorDep,
    service: PermissionResourceServiceDep,
) -> JSONResponse:
    """分页列出权限资源（五种类型统一列表，按类型 / 父节点 / 状态 / 关键字过滤）。

    `parentId` 的三态语义见 `PermissionResourceListQuery`：
    不传 = 不过滤，`0` = 只看顶级，具体 ID = 该父节点的直接子节点。
    """
    page = await service.list_resources(
        actor=actor,
        resource_type=query.resourceType,
        parent_id=query.parentId,
        status=query.status,
        keyword=query.keyword,
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(_page_response(page))


@router.post(
    "/permission-resources",
    summary="创建权限资源",
    dependencies=_manage_dependency(AuditAction.PERMISSION_RESOURCE_CREATE),
)
async def create_permission_resource(
    payload: PermissionResourceCreateRequest,
    actor: CurrentActorDep,
    service: PermissionResourceServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """创建 Page / Menu / Button / API / Field 资源。

    类型专属字段的形状规则由**服务层**校验（与数据库 CHECK 同一份规则，
    见 `app.models.permission.TYPE_REQUIRED_COLUMNS`）——
    schema 层刻意不做互斥校验，避免"两处各写一套形状规则"后必然出现的漂移。
    """
    resource = await service.create(
        actor=actor,
        resource_type=payload.resource_type,
        resource_code=payload.resource_code,
        resource_name=payload.resource_name,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
        status=payload.status,
        route_path=payload.route_path,
        component_path=payload.component_path,
        icon=payload.icon,
        api_method=payload.api_method.value if payload.api_method is not None else None,
        api_path=payload.api_path,
        field_key=payload.field_key,
        owner_resource_id=payload.owner_resource_id,
    )
    await session.commit()
    return success_response(_resource_response(resource))


# ⚠️ `/tree` 必须在 `/{resource_id}` **之前**声明，否则会被后者捕获（见模块说明）。
@router.get(
    "/permission-resources/tree",
    summary="权限资源树（主要用于 MENU 导航树）",
    dependencies=_manage_dependency(AuditAction.PERMISSION_RESOURCE_READ),
)
async def permission_resource_tree(
    query: Annotated[PermissionResourceListQuery, Query()],
    actor: CurrentActorDep,
    service: PermissionResourceServiceDep,
) -> JSONResponse:
    """返回某类型的资源树（`resourceType` 必填）。

    数据里存在环时构树仍会终止并把环内节点提升为根（见服务层实现），
    因此本端点不会因为一条脏数据而挂死请求。
    """
    if query.resourceType is None:
        # 不指定类型时"构树"没有意义（五种类型的树彼此独立），
        # 给一个明确的 400 而不是返回空数组 —— 后者会让调用方以为"确实没有资源"。
        raise BadRequestError("resourceType 为必填参数")
    nodes = await service.tree(actor=actor, resource_type=query.resourceType)
    return success_response([_tree_response(node) for node in nodes])


@router.get(
    "/permission-resources/{resource_id}",
    summary="权限资源详情",
    dependencies=_manage_dependency(AuditAction.PERMISSION_RESOURCE_READ),
)
async def get_permission_resource(
    resource_id: int,
    actor: CurrentActorDep,
    service: PermissionResourceServiceDep,
) -> JSONResponse:
    """按 ID 读取权限资源。"""
    resource = await service.get(actor=actor, resource_id=resource_id)
    return success_response(_resource_response(resource))


@router.put(
    "/permission-resources/{resource_id}",
    summary="修改权限资源",
    dependencies=_manage_dependency(AuditAction.PERMISSION_RESOURCE_UPDATE),
)
async def update_permission_resource(
    resource_id: int,
    payload: PermissionResourceUpdateRequest,
    actor: CurrentActorDep,
    service: PermissionResourceServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """修改资源的展示属性与状态。

    `resource_type` / `resource_code` / `parent_id` / `owner_resource_id`
    均不可修改（理由见 `PermissionResourceUpdateRequest`）：
    改类型等于把已有角色授权静默重新解释成另一类权限。

    把 `status` 改成 `DISABLED` 是**权限变更**的一种（该资源立即退出所有
    角色的有效权限），服务层会递增权限版本（`11 §2`）。
    """
    resource = await service.update(
        actor=actor,
        resource_id=resource_id,
        resource_name=payload.resource_name,
        sort_order=payload.sort_order,
        status=payload.status,
        route_path=payload.route_path,
        component_path=payload.component_path,
        icon=payload.icon,
        api_method=payload.api_method.value if payload.api_method is not None else None,
        api_path=payload.api_path,
        field_key=payload.field_key,
    )
    await session.commit()
    return success_response(_resource_response(resource))


@router.post(
    "/permission-resources/{resource_id}/delete",
    summary="删除权限资源（逻辑删除，带引用检查）",
    dependencies=_manage_dependency(AuditAction.PERMISSION_RESOURCE_DELETE),
)
async def delete_permission_resource(
    resource_id: int,
    actor: CurrentActorDep,
    service: PermissionResourceServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """逻辑删除资源。

    仍被子资源 / 菜单-页面关联 / 角色授权引用时**拒绝**（409）而不是级联清理：
    资源是被授权方引用的**目标**，静默清理会同时改变多个角色的有效权限，
    影响面不可见。拒绝则强制管理员显式决定（与 `03 §4` 的取向一致）。
    """
    resource = await service.delete(actor=actor, resource_id=resource_id)
    await session.commit()
    return success_response(_resource_response(resource))


@router.get(
    "/permission-resources/{resource_id}/pages",
    summary="读取 Menu 关联的 Page",
    dependencies=_manage_dependency(AuditAction.PERMISSION_RESOURCE_READ),
)
async def list_menu_pages(
    resource_id: int,
    actor: CurrentActorDep,
    service: PermissionResourceServiceDep,
) -> JSONResponse:
    """读取该 MENU 关联的全部 Page（`00 §1#4` 一个 Menu 可关联多个 Page）。"""
    pages = await service.list_menu_pages(actor=actor, menu_id=resource_id)
    return success_response(
        MenuPagesResponse(
            menu_id=resource_id,
            pages=[_resource_response(page) for page in pages],
        )
    )


@router.put(
    "/permission-resources/{resource_id}/pages",
    summary="整体替换 Menu 关联的 Page",
    dependencies=_manage_dependency(AuditAction.PERMISSION_RESOURCE_UPDATE),
)
async def replace_menu_pages(
    resource_id: int,
    payload: MenuPagesUpdateRequest,
    actor: CurrentActorDep,
    service: PermissionResourceServiceDep,
    session: DbSessionDep,
) -> JSONResponse:
    """**整体替换** Menu → Page 关联（PUT 语义幂等，before/after 完整落审计）。

    空数组表示解除全部关联；包含非 PAGE 类型或不存在的资源会被拒绝（400）。

    注意该操作**不改变任何后端判权结果**（判权只认 Page，`09 §4`），
    只影响导航渲染；但服务层仍递增权限版本，以便前端及时刷新菜单。
    """
    await service.set_menu_pages(
        actor=actor,
        menu_id=resource_id,
        page_ids=frozenset(payload.pageIds),
    )
    await session.commit()
    pages = await service.list_menu_pages(actor=actor, menu_id=resource_id)
    return success_response(
        MenuPagesResponse(
            menu_id=resource_id,
            pages=[_resource_response(page) for page in pages],
        )
    )


__all__ = ["router"]
