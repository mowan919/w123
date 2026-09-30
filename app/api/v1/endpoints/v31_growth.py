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
from app.models.growth import (
    BizAchievement,
    BizCosmetic,
    BizGrowthEvent,
    BizGrowthRule,
    BizPointRule,
    BizTask,
    BizUserAchievement,
    BizUserCosmetic,
    BizUserEquipment,
    BizUserGrowthAccount,
    BizUserGrowthTransaction,
    BizUserLevelBenefit,
    BizUserLevelHistory,
    BizUserPointAccount,
    BizUserPointTransaction,
    BizUserTask,
)
from app.schemas.v31_growth import (
    BizAchievementCreateRequest,
    BizAchievementListQuery,
    BizAchievementPageResponse,
    BizAchievementResponse,
    BizAchievementUpdateRequest,
    BizCosmeticCreateRequest,
    BizCosmeticListQuery,
    BizCosmeticPageResponse,
    BizCosmeticResponse,
    BizCosmeticUpdateRequest,
    BizGrowthEventCreateRequest,
    BizGrowthEventListQuery,
    BizGrowthEventPageResponse,
    BizGrowthEventResponse,
    BizGrowthEventUpdateRequest,
    BizGrowthRuleCreateRequest,
    BizGrowthRuleListQuery,
    BizGrowthRulePageResponse,
    BizGrowthRuleResponse,
    BizGrowthRuleUpdateRequest,
    BizPointRuleCreateRequest,
    BizPointRuleListQuery,
    BizPointRulePageResponse,
    BizPointRuleResponse,
    BizPointRuleUpdateRequest,
    BizTaskCreateRequest,
    BizTaskListQuery,
    BizTaskPageResponse,
    BizTaskResponse,
    BizTaskUpdateRequest,
    BizUserAchievementCreateRequest,
    BizUserAchievementListQuery,
    BizUserAchievementPageResponse,
    BizUserAchievementResponse,
    BizUserAchievementUpdateRequest,
    BizUserCosmeticCreateRequest,
    BizUserCosmeticListQuery,
    BizUserCosmeticPageResponse,
    BizUserCosmeticResponse,
    BizUserCosmeticUpdateRequest,
    BizUserEquipmentCreateRequest,
    BizUserEquipmentListQuery,
    BizUserEquipmentPageResponse,
    BizUserEquipmentResponse,
    BizUserEquipmentUpdateRequest,
    BizUserGrowthAccountCreateRequest,
    BizUserGrowthAccountListQuery,
    BizUserGrowthAccountPageResponse,
    BizUserGrowthAccountResponse,
    BizUserGrowthAccountUpdateRequest,
    BizUserGrowthTransactionCreateRequest,
    BizUserGrowthTransactionListQuery,
    BizUserGrowthTransactionPageResponse,
    BizUserGrowthTransactionResponse,
    BizUserGrowthTransactionUpdateRequest,
    BizUserLevelBenefitCreateRequest,
    BizUserLevelBenefitListQuery,
    BizUserLevelBenefitPageResponse,
    BizUserLevelBenefitResponse,
    BizUserLevelBenefitUpdateRequest,
    BizUserLevelHistoryCreateRequest,
    BizUserLevelHistoryListQuery,
    BizUserLevelHistoryPageResponse,
    BizUserLevelHistoryResponse,
    BizUserLevelHistoryUpdateRequest,
    BizUserPointAccountCreateRequest,
    BizUserPointAccountListQuery,
    BizUserPointAccountPageResponse,
    BizUserPointAccountResponse,
    BizUserPointAccountUpdateRequest,
    BizUserPointTransactionCreateRequest,
    BizUserPointTransactionListQuery,
    BizUserPointTransactionPageResponse,
    BizUserPointTransactionResponse,
    BizUserPointTransactionUpdateRequest,
    BizUserTaskCreateRequest,
    BizUserTaskListQuery,
    BizUserTaskPageResponse,
    BizUserTaskResponse,
    BizUserTaskUpdateRequest,
)
from app.services.authorization import ApiPermissionCode

ROUTER = APIRouter()

_router_biz_achievement = APIRouter(prefix="/biz-achievement", tags=["growth"])


@_router_biz_achievement.get(
    "",
    summary="BizAchievement 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_achievement",
            )
        ),
    ],
)
async def list_biz_achievement(
    query: Annotated[BizAchievementListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizAchievement,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_achievement",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizAchievementPageResponse(
            list=[BizAchievementResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_achievement.get(
    "/{entity_id}",
    summary="BizAchievement 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_achievement",
            )
        ),
    ],
)
async def get_biz_achievement(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizAchievement,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_achievement",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizAchievementResponse.model_validate(inst))


@_router_biz_achievement.post(
    "",
    summary="BizAchievement 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_achievement",
            )
        ),
    ],
)
async def create_biz_achievement(
    payload: BizAchievementCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizAchievement,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_achievement",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizAchievementResponse.model_validate(inst))


@_router_biz_achievement.put(
    "/{entity_id}",
    summary="BizAchievement 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_achievement",
            )
        ),
    ],
)
async def update_biz_achievement(
    entity_id: int,
    payload: BizAchievementUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizAchievement,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_achievement",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizAchievementResponse.model_validate(inst))


@_router_biz_achievement.delete(
    "/{entity_id}",
    summary="BizAchievement 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_achievement",
            )
        ),
    ],
)
async def delete_biz_achievement(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizAchievement,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_achievement",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizAchievementResponse.model_validate(inst))


ROUTER.include_router(_router_biz_achievement)

_router_biz_cosmetic = APIRouter(prefix="/biz-cosmetic", tags=["growth"])


@_router_biz_cosmetic.get(
    "",
    summary="BizCosmetic 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_cosmetic",
            )
        ),
    ],
)
async def list_biz_cosmetic(
    query: Annotated[BizCosmeticListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizCosmetic,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_cosmetic",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizCosmeticPageResponse(
            list=[BizCosmeticResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_cosmetic.get(
    "/{entity_id}",
    summary="BizCosmetic 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_cosmetic",
            )
        ),
    ],
)
async def get_biz_cosmetic(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizCosmetic,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_cosmetic",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizCosmeticResponse.model_validate(inst))


@_router_biz_cosmetic.post(
    "",
    summary="BizCosmetic 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_cosmetic",
            )
        ),
    ],
)
async def create_biz_cosmetic(
    payload: BizCosmeticCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizCosmetic,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_cosmetic",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizCosmeticResponse.model_validate(inst))


@_router_biz_cosmetic.put(
    "/{entity_id}",
    summary="BizCosmetic 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_cosmetic",
            )
        ),
    ],
)
async def update_biz_cosmetic(
    entity_id: int,
    payload: BizCosmeticUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizCosmetic,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_cosmetic",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizCosmeticResponse.model_validate(inst))


@_router_biz_cosmetic.delete(
    "/{entity_id}",
    summary="BizCosmetic 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_cosmetic",
            )
        ),
    ],
)
async def delete_biz_cosmetic(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizCosmetic,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_cosmetic",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizCosmeticResponse.model_validate(inst))


ROUTER.include_router(_router_biz_cosmetic)

_router_biz_growth_event = APIRouter(prefix="/biz-growth-event", tags=["growth"])


@_router_biz_growth_event.get(
    "",
    summary="BizGrowthEvent 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_growth_event",
            )
        ),
    ],
)
async def list_biz_growth_event(
    query: Annotated[BizGrowthEventListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizGrowthEvent,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_growth_event",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizGrowthEventPageResponse(
            list=[BizGrowthEventResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_growth_event.get(
    "/{entity_id}",
    summary="BizGrowthEvent 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_growth_event",
            )
        ),
    ],
)
async def get_biz_growth_event(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizGrowthEvent,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_growth_event",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizGrowthEventResponse.model_validate(inst))


@_router_biz_growth_event.post(
    "",
    summary="BizGrowthEvent 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_growth_event",
            )
        ),
    ],
)
async def create_biz_growth_event(
    payload: BizGrowthEventCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizGrowthEvent,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_growth_event",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizGrowthEventResponse.model_validate(inst))


@_router_biz_growth_event.put(
    "/{entity_id}",
    summary="BizGrowthEvent 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_growth_event",
            )
        ),
    ],
)
async def update_biz_growth_event(
    entity_id: int,
    payload: BizGrowthEventUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizGrowthEvent,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_growth_event",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizGrowthEventResponse.model_validate(inst))


@_router_biz_growth_event.delete(
    "/{entity_id}",
    summary="BizGrowthEvent 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_growth_event",
            )
        ),
    ],
)
async def delete_biz_growth_event(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizGrowthEvent,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_growth_event",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizGrowthEventResponse.model_validate(inst))


ROUTER.include_router(_router_biz_growth_event)

_router_biz_growth_rule = APIRouter(prefix="/biz-growth-rule", tags=["growth"])


@_router_biz_growth_rule.get(
    "",
    summary="BizGrowthRule 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_growth_rule",
            )
        ),
    ],
)
async def list_biz_growth_rule(
    query: Annotated[BizGrowthRuleListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizGrowthRule,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_growth_rule",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizGrowthRulePageResponse(
            list=[BizGrowthRuleResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_growth_rule.get(
    "/{entity_id}",
    summary="BizGrowthRule 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_growth_rule",
            )
        ),
    ],
)
async def get_biz_growth_rule(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizGrowthRule,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_growth_rule",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizGrowthRuleResponse.model_validate(inst))


@_router_biz_growth_rule.post(
    "",
    summary="BizGrowthRule 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_growth_rule",
            )
        ),
    ],
)
async def create_biz_growth_rule(
    payload: BizGrowthRuleCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizGrowthRule,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_growth_rule",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizGrowthRuleResponse.model_validate(inst))


@_router_biz_growth_rule.put(
    "/{entity_id}",
    summary="BizGrowthRule 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_growth_rule",
            )
        ),
    ],
)
async def update_biz_growth_rule(
    entity_id: int,
    payload: BizGrowthRuleUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizGrowthRule,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_growth_rule",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizGrowthRuleResponse.model_validate(inst))


@_router_biz_growth_rule.delete(
    "/{entity_id}",
    summary="BizGrowthRule 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_growth_rule",
            )
        ),
    ],
)
async def delete_biz_growth_rule(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizGrowthRule,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_growth_rule",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizGrowthRuleResponse.model_validate(inst))


ROUTER.include_router(_router_biz_growth_rule)

_router_biz_point_rule = APIRouter(prefix="/biz-point-rule", tags=["growth"])


@_router_biz_point_rule.get(
    "",
    summary="BizPointRule 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_point_rule",
            )
        ),
    ],
)
async def list_biz_point_rule(
    query: Annotated[BizPointRuleListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizPointRule,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_point_rule",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizPointRulePageResponse(
            list=[BizPointRuleResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_point_rule.get(
    "/{entity_id}",
    summary="BizPointRule 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_point_rule",
            )
        ),
    ],
)
async def get_biz_point_rule(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizPointRule,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_point_rule",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizPointRuleResponse.model_validate(inst))


@_router_biz_point_rule.post(
    "",
    summary="BizPointRule 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_point_rule",
            )
        ),
    ],
)
async def create_biz_point_rule(
    payload: BizPointRuleCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizPointRule,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_point_rule",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizPointRuleResponse.model_validate(inst))


@_router_biz_point_rule.put(
    "/{entity_id}",
    summary="BizPointRule 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_point_rule",
            )
        ),
    ],
)
async def update_biz_point_rule(
    entity_id: int,
    payload: BizPointRuleUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizPointRule,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_point_rule",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizPointRuleResponse.model_validate(inst))


@_router_biz_point_rule.delete(
    "/{entity_id}",
    summary="BizPointRule 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_point_rule",
            )
        ),
    ],
)
async def delete_biz_point_rule(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizPointRule,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_point_rule",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizPointRuleResponse.model_validate(inst))


ROUTER.include_router(_router_biz_point_rule)

_router_biz_task = APIRouter(prefix="/biz-task", tags=["growth"])


@_router_biz_task.get(
    "",
    summary="BizTask 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_task",
            )
        ),
    ],
)
async def list_biz_task(
    query: Annotated[BizTaskListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizTask,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_task",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizTaskPageResponse(
            list=[BizTaskResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_task.get(
    "/{entity_id}",
    summary="BizTask 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_task",
            )
        ),
    ],
)
async def get_biz_task(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizTask,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_task",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizTaskResponse.model_validate(inst))


@_router_biz_task.post(
    "",
    summary="BizTask 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_task",
            )
        ),
    ],
)
async def create_biz_task(
    payload: BizTaskCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizTask,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_task",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizTaskResponse.model_validate(inst))


@_router_biz_task.put(
    "/{entity_id}",
    summary="BizTask 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_task",
            )
        ),
    ],
)
async def update_biz_task(
    entity_id: int,
    payload: BizTaskUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizTask,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_task",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizTaskResponse.model_validate(inst))


@_router_biz_task.delete(
    "/{entity_id}",
    summary="BizTask 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_task",
            )
        ),
    ],
)
async def delete_biz_task(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizTask,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_task",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizTaskResponse.model_validate(inst))


ROUTER.include_router(_router_biz_task)

_router_biz_user_achievement = APIRouter(prefix="/biz-user-achievement", tags=["growth"])


@_router_biz_user_achievement.get(
    "",
    summary="BizUserAchievement 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_achievement",
            )
        ),
    ],
)
async def list_biz_user_achievement(
    query: Annotated[BizUserAchievementListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserAchievement,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_achievement",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserAchievementPageResponse(
            list=[BizUserAchievementResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_achievement.get(
    "/{entity_id}",
    summary="BizUserAchievement 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_achievement",
            )
        ),
    ],
)
async def get_biz_user_achievement(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserAchievement,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_achievement",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserAchievementResponse.model_validate(inst))


@_router_biz_user_achievement.post(
    "",
    summary="BizUserAchievement 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_user_achievement",
            )
        ),
    ],
)
async def create_biz_user_achievement(
    payload: BizUserAchievementCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserAchievement,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_achievement",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserAchievementResponse.model_validate(inst))


@_router_biz_user_achievement.put(
    "/{entity_id}",
    summary="BizUserAchievement 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_user_achievement",
            )
        ),
    ],
)
async def update_biz_user_achievement(
    entity_id: int,
    payload: BizUserAchievementUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserAchievement,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_achievement",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserAchievementResponse.model_validate(inst))


@_router_biz_user_achievement.delete(
    "/{entity_id}",
    summary="BizUserAchievement 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_user_achievement",
            )
        ),
    ],
)
async def delete_biz_user_achievement(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserAchievement,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_achievement",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserAchievementResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_achievement)

_router_biz_user_cosmetic = APIRouter(prefix="/biz-user-cosmetic", tags=["growth"])


@_router_biz_user_cosmetic.get(
    "",
    summary="BizUserCosmetic 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_cosmetic",
            )
        ),
    ],
)
async def list_biz_user_cosmetic(
    query: Annotated[BizUserCosmeticListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserCosmetic,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_cosmetic",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserCosmeticPageResponse(
            list=[BizUserCosmeticResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_cosmetic.get(
    "/{entity_id}",
    summary="BizUserCosmetic 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_cosmetic",
            )
        ),
    ],
)
async def get_biz_user_cosmetic(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserCosmetic,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_cosmetic",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserCosmeticResponse.model_validate(inst))


@_router_biz_user_cosmetic.post(
    "",
    summary="BizUserCosmetic 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_user_cosmetic",
            )
        ),
    ],
)
async def create_biz_user_cosmetic(
    payload: BizUserCosmeticCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserCosmetic,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_cosmetic",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserCosmeticResponse.model_validate(inst))


@_router_biz_user_cosmetic.put(
    "/{entity_id}",
    summary="BizUserCosmetic 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_user_cosmetic",
            )
        ),
    ],
)
async def update_biz_user_cosmetic(
    entity_id: int,
    payload: BizUserCosmeticUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserCosmetic,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_cosmetic",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserCosmeticResponse.model_validate(inst))


@_router_biz_user_cosmetic.delete(
    "/{entity_id}",
    summary="BizUserCosmetic 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_user_cosmetic",
            )
        ),
    ],
)
async def delete_biz_user_cosmetic(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserCosmetic,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_cosmetic",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserCosmeticResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_cosmetic)

_router_biz_user_equipment = APIRouter(prefix="/biz-user-equipment", tags=["growth"])


@_router_biz_user_equipment.get(
    "",
    summary="BizUserEquipment 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_equipment",
            )
        ),
    ],
)
async def list_biz_user_equipment(
    query: Annotated[BizUserEquipmentListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserEquipment,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_equipment",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserEquipmentPageResponse(
            list=[BizUserEquipmentResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_equipment.get(
    "/{entity_id}",
    summary="BizUserEquipment 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_equipment",
            )
        ),
    ],
)
async def get_biz_user_equipment(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserEquipment,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_equipment",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserEquipmentResponse.model_validate(inst))


@_router_biz_user_equipment.post(
    "",
    summary="BizUserEquipment 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_user_equipment",
            )
        ),
    ],
)
async def create_biz_user_equipment(
    payload: BizUserEquipmentCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserEquipment,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_equipment",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserEquipmentResponse.model_validate(inst))


@_router_biz_user_equipment.put(
    "/{entity_id}",
    summary="BizUserEquipment 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_user_equipment",
            )
        ),
    ],
)
async def update_biz_user_equipment(
    entity_id: int,
    payload: BizUserEquipmentUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserEquipment,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_equipment",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserEquipmentResponse.model_validate(inst))


@_router_biz_user_equipment.delete(
    "/{entity_id}",
    summary="BizUserEquipment 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_user_equipment",
            )
        ),
    ],
)
async def delete_biz_user_equipment(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserEquipment,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_equipment",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserEquipmentResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_equipment)

_router_biz_user_growth_account = APIRouter(prefix="/biz-user-growth-account", tags=["growth"])


@_router_biz_user_growth_account.get(
    "",
    summary="BizUserGrowthAccount 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_growth_account",
            )
        ),
    ],
)
async def list_biz_user_growth_account(
    query: Annotated[BizUserGrowthAccountListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserGrowthAccount,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_growth_account",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserGrowthAccountPageResponse(
            list=[BizUserGrowthAccountResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_growth_account.get(
    "/{entity_id}",
    summary="BizUserGrowthAccount 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_growth_account",
            )
        ),
    ],
)
async def get_biz_user_growth_account(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserGrowthAccount,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_growth_account",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserGrowthAccountResponse.model_validate(inst))


@_router_biz_user_growth_account.post(
    "",
    summary="BizUserGrowthAccount 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_user_growth_account",
            )
        ),
    ],
)
async def create_biz_user_growth_account(
    payload: BizUserGrowthAccountCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserGrowthAccount,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_growth_account",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserGrowthAccountResponse.model_validate(inst))


@_router_biz_user_growth_account.put(
    "/{entity_id}",
    summary="BizUserGrowthAccount 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_user_growth_account",
            )
        ),
    ],
)
async def update_biz_user_growth_account(
    entity_id: int,
    payload: BizUserGrowthAccountUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserGrowthAccount,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_growth_account",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserGrowthAccountResponse.model_validate(inst))


@_router_biz_user_growth_account.delete(
    "/{entity_id}",
    summary="BizUserGrowthAccount 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_user_growth_account",
            )
        ),
    ],
)
async def delete_biz_user_growth_account(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserGrowthAccount,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_growth_account",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserGrowthAccountResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_growth_account)

_router_biz_user_growth_transaction = APIRouter(
    prefix="/biz-user-growth-transaction", tags=["growth"]
)


@_router_biz_user_growth_transaction.get(
    "",
    summary="BizUserGrowthTransaction 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_growth_transaction",
            )
        ),
    ],
)
async def list_biz_user_growth_transaction(
    query: Annotated[BizUserGrowthTransactionListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserGrowthTransaction,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_growth_transaction",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserGrowthTransactionPageResponse(
            list=[BizUserGrowthTransactionResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_growth_transaction.get(
    "/{entity_id}",
    summary="BizUserGrowthTransaction 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_growth_transaction",
            )
        ),
    ],
)
async def get_biz_user_growth_transaction(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserGrowthTransaction,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_growth_transaction",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserGrowthTransactionResponse.model_validate(inst))


@_router_biz_user_growth_transaction.post(
    "",
    summary="BizUserGrowthTransaction 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_user_growth_transaction",
            )
        ),
    ],
)
async def create_biz_user_growth_transaction(
    payload: BizUserGrowthTransactionCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserGrowthTransaction,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_growth_transaction",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserGrowthTransactionResponse.model_validate(inst))


@_router_biz_user_growth_transaction.put(
    "/{entity_id}",
    summary="BizUserGrowthTransaction 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_user_growth_transaction",
            )
        ),
    ],
)
async def update_biz_user_growth_transaction(
    entity_id: int,
    payload: BizUserGrowthTransactionUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserGrowthTransaction,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_growth_transaction",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserGrowthTransactionResponse.model_validate(inst))


@_router_biz_user_growth_transaction.delete(
    "/{entity_id}",
    summary="BizUserGrowthTransaction 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_user_growth_transaction",
            )
        ),
    ],
)
async def delete_biz_user_growth_transaction(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserGrowthTransaction,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_growth_transaction",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserGrowthTransactionResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_growth_transaction)

_router_biz_user_level_benefit = APIRouter(prefix="/biz-user-level-benefit", tags=["growth"])


@_router_biz_user_level_benefit.get(
    "",
    summary="BizUserLevelBenefit 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_level_benefit",
            )
        ),
    ],
)
async def list_biz_user_level_benefit(
    query: Annotated[BizUserLevelBenefitListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevelBenefit,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_level_benefit",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserLevelBenefitPageResponse(
            list=[BizUserLevelBenefitResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_level_benefit.get(
    "/{entity_id}",
    summary="BizUserLevelBenefit 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_level_benefit",
            )
        ),
    ],
)
async def get_biz_user_level_benefit(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevelBenefit,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_level_benefit",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserLevelBenefitResponse.model_validate(inst))


@_router_biz_user_level_benefit.post(
    "",
    summary="BizUserLevelBenefit 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_user_level_benefit",
            )
        ),
    ],
)
async def create_biz_user_level_benefit(
    payload: BizUserLevelBenefitCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevelBenefit,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_level_benefit",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserLevelBenefitResponse.model_validate(inst))


@_router_biz_user_level_benefit.put(
    "/{entity_id}",
    summary="BizUserLevelBenefit 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_user_level_benefit",
            )
        ),
    ],
)
async def update_biz_user_level_benefit(
    entity_id: int,
    payload: BizUserLevelBenefitUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevelBenefit,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_level_benefit",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserLevelBenefitResponse.model_validate(inst))


@_router_biz_user_level_benefit.delete(
    "/{entity_id}",
    summary="BizUserLevelBenefit 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_user_level_benefit",
            )
        ),
    ],
)
async def delete_biz_user_level_benefit(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevelBenefit,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_level_benefit",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserLevelBenefitResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_level_benefit)

_router_biz_user_level_history = APIRouter(prefix="/biz-user-level-history", tags=["growth"])


@_router_biz_user_level_history.get(
    "",
    summary="BizUserLevelHistory 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_level_history",
            )
        ),
    ],
)
async def list_biz_user_level_history(
    query: Annotated[BizUserLevelHistoryListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevelHistory,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_level_history",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserLevelHistoryPageResponse(
            list=[BizUserLevelHistoryResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_level_history.get(
    "/{entity_id}",
    summary="BizUserLevelHistory 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_level_history",
            )
        ),
    ],
)
async def get_biz_user_level_history(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevelHistory,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_level_history",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserLevelHistoryResponse.model_validate(inst))


@_router_biz_user_level_history.post(
    "",
    summary="BizUserLevelHistory 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_user_level_history",
            )
        ),
    ],
)
async def create_biz_user_level_history(
    payload: BizUserLevelHistoryCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevelHistory,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_level_history",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserLevelHistoryResponse.model_validate(inst))


@_router_biz_user_level_history.put(
    "/{entity_id}",
    summary="BizUserLevelHistory 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_user_level_history",
            )
        ),
    ],
)
async def update_biz_user_level_history(
    entity_id: int,
    payload: BizUserLevelHistoryUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevelHistory,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_level_history",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserLevelHistoryResponse.model_validate(inst))


@_router_biz_user_level_history.delete(
    "/{entity_id}",
    summary="BizUserLevelHistory 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_user_level_history",
            )
        ),
    ],
)
async def delete_biz_user_level_history(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevelHistory,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_level_history",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserLevelHistoryResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_level_history)

_router_biz_user_point_account = APIRouter(prefix="/biz-user-point-account", tags=["growth"])


@_router_biz_user_point_account.get(
    "",
    summary="BizUserPointAccount 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_point_account",
            )
        ),
    ],
)
async def list_biz_user_point_account(
    query: Annotated[BizUserPointAccountListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPointAccount,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_point_account",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserPointAccountPageResponse(
            list=[BizUserPointAccountResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_point_account.get(
    "/{entity_id}",
    summary="BizUserPointAccount 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_point_account",
            )
        ),
    ],
)
async def get_biz_user_point_account(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPointAccount,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_point_account",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserPointAccountResponse.model_validate(inst))


@_router_biz_user_point_account.post(
    "",
    summary="BizUserPointAccount 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_user_point_account",
            )
        ),
    ],
)
async def create_biz_user_point_account(
    payload: BizUserPointAccountCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPointAccount,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_point_account",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserPointAccountResponse.model_validate(inst))


@_router_biz_user_point_account.put(
    "/{entity_id}",
    summary="BizUserPointAccount 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_user_point_account",
            )
        ),
    ],
)
async def update_biz_user_point_account(
    entity_id: int,
    payload: BizUserPointAccountUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPointAccount,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_point_account",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserPointAccountResponse.model_validate(inst))


@_router_biz_user_point_account.delete(
    "/{entity_id}",
    summary="BizUserPointAccount 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_user_point_account",
            )
        ),
    ],
)
async def delete_biz_user_point_account(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPointAccount,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_point_account",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserPointAccountResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_point_account)

_router_biz_user_point_transaction = APIRouter(
    prefix="/biz-user-point-transaction", tags=["growth"]
)


@_router_biz_user_point_transaction.get(
    "",
    summary="BizUserPointTransaction 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_point_transaction",
            )
        ),
    ],
)
async def list_biz_user_point_transaction(
    query: Annotated[BizUserPointTransactionListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPointTransaction,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_point_transaction",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserPointTransactionPageResponse(
            list=[BizUserPointTransactionResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_point_transaction.get(
    "/{entity_id}",
    summary="BizUserPointTransaction 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_point_transaction",
            )
        ),
    ],
)
async def get_biz_user_point_transaction(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPointTransaction,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_point_transaction",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserPointTransactionResponse.model_validate(inst))


@_router_biz_user_point_transaction.post(
    "",
    summary="BizUserPointTransaction 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_user_point_transaction",
            )
        ),
    ],
)
async def create_biz_user_point_transaction(
    payload: BizUserPointTransactionCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPointTransaction,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_point_transaction",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserPointTransactionResponse.model_validate(inst))


@_router_biz_user_point_transaction.put(
    "/{entity_id}",
    summary="BizUserPointTransaction 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_user_point_transaction",
            )
        ),
    ],
)
async def update_biz_user_point_transaction(
    entity_id: int,
    payload: BizUserPointTransactionUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPointTransaction,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_point_transaction",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserPointTransactionResponse.model_validate(inst))


@_router_biz_user_point_transaction.delete(
    "/{entity_id}",
    summary="BizUserPointTransaction 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_user_point_transaction",
            )
        ),
    ],
)
async def delete_biz_user_point_transaction(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPointTransaction,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_point_transaction",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserPointTransactionResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_point_transaction)

_router_biz_user_task = APIRouter(prefix="/biz-user-task", tags=["growth"])


@_router_biz_user_task.get(
    "",
    summary="BizUserTask 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_task",
            )
        ),
    ],
)
async def list_biz_user_task(
    query: Annotated[BizUserTaskListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserTask,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_task",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserTaskPageResponse(
            list=[BizUserTaskResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_task.get(
    "/{entity_id}",
    summary="BizUserTask 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_READ,
                resource_type="biz_user_task",
            )
        ),
    ],
)
async def get_biz_user_task(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserTask,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_task",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserTaskResponse.model_validate(inst))


@_router_biz_user_task.post(
    "",
    summary="BizUserTask 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_CREATE,
                resource_type="biz_user_task",
            )
        ),
    ],
)
async def create_biz_user_task(
    payload: BizUserTaskCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserTask,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_task",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserTaskResponse.model_validate(inst))


@_router_biz_user_task.put(
    "/{entity_id}",
    summary="BizUserTask 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_UPDATE,
                resource_type="biz_user_task",
            )
        ),
    ],
)
async def update_biz_user_task(
    entity_id: int,
    payload: BizUserTaskUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserTask,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_task",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserTaskResponse.model_validate(inst))


@_router_biz_user_task.delete(
    "/{entity_id}",
    summary="BizUserTask 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.GROWTH_MANAGE,
                action=AuditAction.GROWTH_DELETE,
                resource_type="biz_user_task",
            )
        ),
    ],
)
async def delete_biz_user_task(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserTask,
        permission_code=ApiPermissionCode.GROWTH_MANAGE,
        resource_type="biz_user_task",
        audit_create=AuditAction.GROWTH_CREATE,
        audit_update=AuditAction.GROWTH_UPDATE,
        audit_delete=AuditAction.GROWTH_DELETE,
        audit_read=AuditAction.GROWTH_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserTaskResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_task)


__all__ = [
    "ROUTER",
]
