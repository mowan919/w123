"""V3.1 结构层 CRUD 端点（VCTN §33，自动生成）。

每个实体一组 `APIRouter`（仅 list/get/create/update/delete），
复用 `app.crud.base.BaseCrudService`；权限门 + 审计由底座与路由级依赖共同承担。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.api.deps import CurrentActorDep, DbSessionDep, require_api_permission
from app.audit import AuditAction
from app.audit.buffer import BufferingAuditRecorder
from app.core.response import success_response
from app.crud.base import BaseCrudService
from app.models.tool import (
    Tool,
    ToolAccessPolicy,
    ToolCategory,
    ToolComponentRegistry,
    ToolPopularityDaily,
    ToolRecentUsage,
    ToolUsageDaily,
    ToolUsageEvent,
    ToolVersion,
)
from app.schemas.v31_tool import (
    ToolAccessPolicyCreateRequest,
    ToolAccessPolicyListQuery,
    ToolAccessPolicyPageResponse,
    ToolAccessPolicyResponse,
    ToolAccessPolicyUpdateRequest,
    ToolCategoryCreateRequest,
    ToolCategoryListQuery,
    ToolCategoryPageResponse,
    ToolCategoryResponse,
    ToolCategoryUpdateRequest,
    ToolComponentRegistryCreateRequest,
    ToolComponentRegistryListQuery,
    ToolComponentRegistryPageResponse,
    ToolComponentRegistryResponse,
    ToolComponentRegistryUpdateRequest,
    ToolCreateRequest,
    ToolListQuery,
    ToolPageResponse,
    ToolPopularityDailyCreateRequest,
    ToolPopularityDailyListQuery,
    ToolPopularityDailyPageResponse,
    ToolPopularityDailyResponse,
    ToolPopularityDailyUpdateRequest,
    ToolRecentUsageCreateRequest,
    ToolRecentUsageListQuery,
    ToolRecentUsagePageResponse,
    ToolRecentUsageResponse,
    ToolRecentUsageUpdateRequest,
    ToolResponse,
    ToolUpdateRequest,
    ToolUsageDailyCreateRequest,
    ToolUsageDailyListQuery,
    ToolUsageDailyPageResponse,
    ToolUsageDailyResponse,
    ToolUsageDailyUpdateRequest,
    ToolUsageEventCreateRequest,
    ToolUsageEventListQuery,
    ToolUsageEventPageResponse,
    ToolUsageEventResponse,
    ToolUsageEventUpdateRequest,
    ToolVersionCreateRequest,
    ToolVersionListQuery,
    ToolVersionPageResponse,
    ToolVersionResponse,
    ToolVersionUpdateRequest,
)
from app.services.authorization import ApiPermissionCode

ROUTER = APIRouter()

_router_tool = APIRouter(prefix="/tool", tags=["tool"])


@_router_tool.get(
    "",
    summary="Tool 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool",
            )
        ),
    ],
)
async def list_tool(
    query: Annotated[ToolListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=Tool,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        ToolPageResponse(
            list=[ToolResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_tool.get(
    "/{entity_id}",
    summary="Tool 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool",
            )
        ),
    ],
)
async def get_tool(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=Tool,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(ToolResponse.model_validate(inst))


@_router_tool.post(
    "",
    summary="Tool 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_CREATE,
                resource_type="tool",
            )
        ),
    ],
)
async def create_tool(
    payload: ToolCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=Tool,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(ToolResponse.model_validate(inst))


@_router_tool.put(
    "/{entity_id}",
    summary="Tool 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_UPDATE,
                resource_type="tool",
            )
        ),
    ],
)
async def update_tool(
    entity_id: int,
    payload: ToolUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=Tool,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(ToolResponse.model_validate(inst))


@_router_tool.delete(
    "/{entity_id}",
    summary="Tool 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_DELETE,
                resource_type="tool",
            )
        ),
    ],
)
async def delete_tool(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=Tool,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(ToolResponse.model_validate(inst))


ROUTER.include_router(_router_tool)

_router_tool_access_policy = APIRouter(prefix="/tool-access-policy", tags=["tool"])


@_router_tool_access_policy.get(
    "",
    summary="ToolAccessPolicy 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_access_policy",
            )
        ),
    ],
)
async def list_tool_access_policy(
    query: Annotated[ToolAccessPolicyListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolAccessPolicy,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_access_policy",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        ToolAccessPolicyPageResponse(
            list=[ToolAccessPolicyResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_tool_access_policy.get(
    "/{entity_id}",
    summary="ToolAccessPolicy 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_access_policy",
            )
        ),
    ],
)
async def get_tool_access_policy(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolAccessPolicy,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_access_policy",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(ToolAccessPolicyResponse.model_validate(inst))


@_router_tool_access_policy.post(
    "",
    summary="ToolAccessPolicy 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_CREATE,
                resource_type="tool_access_policy",
            )
        ),
    ],
)
async def create_tool_access_policy(
    payload: ToolAccessPolicyCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolAccessPolicy,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_access_policy",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(ToolAccessPolicyResponse.model_validate(inst))


@_router_tool_access_policy.put(
    "/{entity_id}",
    summary="ToolAccessPolicy 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_UPDATE,
                resource_type="tool_access_policy",
            )
        ),
    ],
)
async def update_tool_access_policy(
    entity_id: int,
    payload: ToolAccessPolicyUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolAccessPolicy,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_access_policy",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(ToolAccessPolicyResponse.model_validate(inst))


@_router_tool_access_policy.delete(
    "/{entity_id}",
    summary="ToolAccessPolicy 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_DELETE,
                resource_type="tool_access_policy",
            )
        ),
    ],
)
async def delete_tool_access_policy(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolAccessPolicy,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_access_policy",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(ToolAccessPolicyResponse.model_validate(inst))


ROUTER.include_router(_router_tool_access_policy)

_router_tool_category = APIRouter(prefix="/tool-category", tags=["tool"])


@_router_tool_category.get(
    "",
    summary="ToolCategory 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_category",
            )
        ),
    ],
)
async def list_tool_category(
    query: Annotated[ToolCategoryListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolCategory,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_category",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        ToolCategoryPageResponse(
            list=[ToolCategoryResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_tool_category.get(
    "/{entity_id}",
    summary="ToolCategory 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_category",
            )
        ),
    ],
)
async def get_tool_category(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolCategory,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_category",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(ToolCategoryResponse.model_validate(inst))


@_router_tool_category.post(
    "",
    summary="ToolCategory 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_CREATE,
                resource_type="tool_category",
            )
        ),
    ],
)
async def create_tool_category(
    payload: ToolCategoryCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolCategory,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_category",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(ToolCategoryResponse.model_validate(inst))


@_router_tool_category.put(
    "/{entity_id}",
    summary="ToolCategory 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_UPDATE,
                resource_type="tool_category",
            )
        ),
    ],
)
async def update_tool_category(
    entity_id: int,
    payload: ToolCategoryUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolCategory,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_category",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(ToolCategoryResponse.model_validate(inst))


@_router_tool_category.delete(
    "/{entity_id}",
    summary="ToolCategory 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_DELETE,
                resource_type="tool_category",
            )
        ),
    ],
)
async def delete_tool_category(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolCategory,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_category",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(ToolCategoryResponse.model_validate(inst))


ROUTER.include_router(_router_tool_category)

_router_tool_component_registry = APIRouter(prefix="/tool-component-registry", tags=["tool"])


@_router_tool_component_registry.get(
    "",
    summary="ToolComponentRegistry 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_component_registry",
            )
        ),
    ],
)
async def list_tool_component_registry(
    query: Annotated[ToolComponentRegistryListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolComponentRegistry,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_component_registry",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        ToolComponentRegistryPageResponse(
            list=[ToolComponentRegistryResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_tool_component_registry.get(
    "/{entity_id}",
    summary="ToolComponentRegistry 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_component_registry",
            )
        ),
    ],
)
async def get_tool_component_registry(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolComponentRegistry,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_component_registry",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(ToolComponentRegistryResponse.model_validate(inst))


@_router_tool_component_registry.post(
    "",
    summary="ToolComponentRegistry 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_CREATE,
                resource_type="tool_component_registry",
            )
        ),
    ],
)
async def create_tool_component_registry(
    payload: ToolComponentRegistryCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolComponentRegistry,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_component_registry",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(ToolComponentRegistryResponse.model_validate(inst))


@_router_tool_component_registry.put(
    "/{entity_id}",
    summary="ToolComponentRegistry 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_UPDATE,
                resource_type="tool_component_registry",
            )
        ),
    ],
)
async def update_tool_component_registry(
    entity_id: int,
    payload: ToolComponentRegistryUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolComponentRegistry,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_component_registry",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(ToolComponentRegistryResponse.model_validate(inst))


@_router_tool_component_registry.delete(
    "/{entity_id}",
    summary="ToolComponentRegistry 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_DELETE,
                resource_type="tool_component_registry",
            )
        ),
    ],
)
async def delete_tool_component_registry(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolComponentRegistry,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_component_registry",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(ToolComponentRegistryResponse.model_validate(inst))


ROUTER.include_router(_router_tool_component_registry)

_router_tool_popularity_daily = APIRouter(prefix="/tool-popularity-daily", tags=["tool"])


@_router_tool_popularity_daily.get(
    "",
    summary="ToolPopularityDaily 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_popularity_daily",
            )
        ),
    ],
)
async def list_tool_popularity_daily(
    query: Annotated[ToolPopularityDailyListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolPopularityDaily,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_popularity_daily",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        ToolPopularityDailyPageResponse(
            list=[ToolPopularityDailyResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_tool_popularity_daily.get(
    "/{entity_id}",
    summary="ToolPopularityDaily 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_popularity_daily",
            )
        ),
    ],
)
async def get_tool_popularity_daily(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolPopularityDaily,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_popularity_daily",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(ToolPopularityDailyResponse.model_validate(inst))


@_router_tool_popularity_daily.post(
    "",
    summary="ToolPopularityDaily 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_CREATE,
                resource_type="tool_popularity_daily",
            )
        ),
    ],
)
async def create_tool_popularity_daily(
    payload: ToolPopularityDailyCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolPopularityDaily,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_popularity_daily",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(ToolPopularityDailyResponse.model_validate(inst))


@_router_tool_popularity_daily.put(
    "/{entity_id}",
    summary="ToolPopularityDaily 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_UPDATE,
                resource_type="tool_popularity_daily",
            )
        ),
    ],
)
async def update_tool_popularity_daily(
    entity_id: int,
    payload: ToolPopularityDailyUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolPopularityDaily,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_popularity_daily",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(ToolPopularityDailyResponse.model_validate(inst))


@_router_tool_popularity_daily.delete(
    "/{entity_id}",
    summary="ToolPopularityDaily 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_DELETE,
                resource_type="tool_popularity_daily",
            )
        ),
    ],
)
async def delete_tool_popularity_daily(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolPopularityDaily,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_popularity_daily",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(ToolPopularityDailyResponse.model_validate(inst))


ROUTER.include_router(_router_tool_popularity_daily)

_router_tool_recent_usage = APIRouter(prefix="/tool-recent-usage", tags=["tool"])


@_router_tool_recent_usage.get(
    "",
    summary="ToolRecentUsage 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_recent_usage",
            )
        ),
    ],
)
async def list_tool_recent_usage(
    query: Annotated[ToolRecentUsageListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolRecentUsage,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_recent_usage",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        ToolRecentUsagePageResponse(
            list=[ToolRecentUsageResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_tool_recent_usage.get(
    "/{entity_id}",
    summary="ToolRecentUsage 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_recent_usage",
            )
        ),
    ],
)
async def get_tool_recent_usage(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolRecentUsage,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_recent_usage",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(ToolRecentUsageResponse.model_validate(inst))


@_router_tool_recent_usage.post(
    "",
    summary="ToolRecentUsage 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_CREATE,
                resource_type="tool_recent_usage",
            )
        ),
    ],
)
async def create_tool_recent_usage(
    payload: ToolRecentUsageCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolRecentUsage,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_recent_usage",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(ToolRecentUsageResponse.model_validate(inst))


@_router_tool_recent_usage.put(
    "/{entity_id}",
    summary="ToolRecentUsage 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_UPDATE,
                resource_type="tool_recent_usage",
            )
        ),
    ],
)
async def update_tool_recent_usage(
    entity_id: int,
    payload: ToolRecentUsageUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolRecentUsage,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_recent_usage",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(ToolRecentUsageResponse.model_validate(inst))


@_router_tool_recent_usage.delete(
    "/{entity_id}",
    summary="ToolRecentUsage 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_DELETE,
                resource_type="tool_recent_usage",
            )
        ),
    ],
)
async def delete_tool_recent_usage(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolRecentUsage,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_recent_usage",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(ToolRecentUsageResponse.model_validate(inst))


ROUTER.include_router(_router_tool_recent_usage)

_router_tool_usage_daily = APIRouter(prefix="/tool-usage-daily", tags=["tool"])


@_router_tool_usage_daily.get(
    "",
    summary="ToolUsageDaily 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_usage_daily",
            )
        ),
    ],
)
async def list_tool_usage_daily(
    query: Annotated[ToolUsageDailyListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolUsageDaily,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_usage_daily",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        ToolUsageDailyPageResponse(
            list=[ToolUsageDailyResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_tool_usage_daily.get(
    "/{entity_id}",
    summary="ToolUsageDaily 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_usage_daily",
            )
        ),
    ],
)
async def get_tool_usage_daily(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolUsageDaily,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_usage_daily",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(ToolUsageDailyResponse.model_validate(inst))


@_router_tool_usage_daily.post(
    "",
    summary="ToolUsageDaily 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_CREATE,
                resource_type="tool_usage_daily",
            )
        ),
    ],
)
async def create_tool_usage_daily(
    payload: ToolUsageDailyCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolUsageDaily,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_usage_daily",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(ToolUsageDailyResponse.model_validate(inst))


@_router_tool_usage_daily.put(
    "/{entity_id}",
    summary="ToolUsageDaily 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_UPDATE,
                resource_type="tool_usage_daily",
            )
        ),
    ],
)
async def update_tool_usage_daily(
    entity_id: int,
    payload: ToolUsageDailyUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolUsageDaily,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_usage_daily",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(ToolUsageDailyResponse.model_validate(inst))


@_router_tool_usage_daily.delete(
    "/{entity_id}",
    summary="ToolUsageDaily 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_DELETE,
                resource_type="tool_usage_daily",
            )
        ),
    ],
)
async def delete_tool_usage_daily(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolUsageDaily,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_usage_daily",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(ToolUsageDailyResponse.model_validate(inst))


ROUTER.include_router(_router_tool_usage_daily)

_router_tool_usage_event = APIRouter(prefix="/tool-usage-event", tags=["tool"])


@_router_tool_usage_event.get(
    "",
    summary="ToolUsageEvent 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_usage_event",
            )
        ),
    ],
)
async def list_tool_usage_event(
    query: Annotated[ToolUsageEventListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolUsageEvent,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_usage_event",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        ToolUsageEventPageResponse(
            list=[ToolUsageEventResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_tool_usage_event.get(
    "/{entity_id}",
    summary="ToolUsageEvent 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_usage_event",
            )
        ),
    ],
)
async def get_tool_usage_event(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolUsageEvent,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_usage_event",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(ToolUsageEventResponse.model_validate(inst))


@_router_tool_usage_event.post(
    "",
    summary="ToolUsageEvent 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_CREATE,
                resource_type="tool_usage_event",
            )
        ),
    ],
)
async def create_tool_usage_event(
    payload: ToolUsageEventCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolUsageEvent,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_usage_event",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(ToolUsageEventResponse.model_validate(inst))


@_router_tool_usage_event.put(
    "/{entity_id}",
    summary="ToolUsageEvent 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_UPDATE,
                resource_type="tool_usage_event",
            )
        ),
    ],
)
async def update_tool_usage_event(
    entity_id: int,
    payload: ToolUsageEventUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolUsageEvent,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_usage_event",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(ToolUsageEventResponse.model_validate(inst))


@_router_tool_usage_event.delete(
    "/{entity_id}",
    summary="ToolUsageEvent 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_DELETE,
                resource_type="tool_usage_event",
            )
        ),
    ],
)
async def delete_tool_usage_event(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolUsageEvent,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_usage_event",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(ToolUsageEventResponse.model_validate(inst))


ROUTER.include_router(_router_tool_usage_event)

_router_tool_version = APIRouter(prefix="/tool-version", tags=["tool"])


@_router_tool_version.get(
    "",
    summary="ToolVersion 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_version",
            )
        ),
    ],
)
async def list_tool_version(
    query: Annotated[ToolVersionListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolVersion,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_version",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        ToolVersionPageResponse(
            list=[ToolVersionResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_tool_version.get(
    "/{entity_id}",
    summary="ToolVersion 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_READ,
                resource_type="tool_version",
            )
        ),
    ],
)
async def get_tool_version(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolVersion,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_version",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(ToolVersionResponse.model_validate(inst))


@_router_tool_version.post(
    "",
    summary="ToolVersion 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_CREATE,
                resource_type="tool_version",
            )
        ),
    ],
)
async def create_tool_version(
    payload: ToolVersionCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolVersion,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_version",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(ToolVersionResponse.model_validate(inst))


@_router_tool_version.put(
    "/{entity_id}",
    summary="ToolVersion 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_UPDATE,
                resource_type="tool_version",
            )
        ),
    ],
)
async def update_tool_version(
    entity_id: int,
    payload: ToolVersionUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolVersion,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_version",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(ToolVersionResponse.model_validate(inst))


@_router_tool_version.delete(
    "/{entity_id}",
    summary="ToolVersion 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.TOOL_MANAGE,
                action=AuditAction.TOOL_DELETE,
                resource_type="tool_version",
            )
        ),
    ],
)
async def delete_tool_version(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=ToolVersion,
        permission_code=ApiPermissionCode.TOOL_MANAGE,
        resource_type="tool_version",
        audit_create=AuditAction.TOOL_CREATE,
        audit_update=AuditAction.TOOL_UPDATE,
        audit_delete=AuditAction.TOOL_DELETE,
        audit_read=AuditAction.TOOL_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(ToolVersionResponse.model_validate(inst))


ROUTER.include_router(_router_tool_version)


__all__ = [
    "ROUTER",
]
