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
from app.models.biz_user import (
    BizUser,
    BizUserLevel,
    BizUserLoginIdentity,
    BizUserLoginLog,
    BizUserPasswordHistory,
    BizUserProfile,
    BizUserSession,
    BizUserVerification,
)
from app.schemas.v31_biz_user import (
    BizUserCreateRequest,
    BizUserLevelCreateRequest,
    BizUserLevelListQuery,
    BizUserLevelPageResponse,
    BizUserLevelResponse,
    BizUserLevelUpdateRequest,
    BizUserListQuery,
    BizUserLoginIdentityCreateRequest,
    BizUserLoginIdentityListQuery,
    BizUserLoginIdentityPageResponse,
    BizUserLoginIdentityResponse,
    BizUserLoginIdentityUpdateRequest,
    BizUserLoginLogCreateRequest,
    BizUserLoginLogListQuery,
    BizUserLoginLogPageResponse,
    BizUserLoginLogResponse,
    BizUserLoginLogUpdateRequest,
    BizUserPageResponse,
    BizUserPasswordHistoryCreateRequest,
    BizUserPasswordHistoryListQuery,
    BizUserPasswordHistoryPageResponse,
    BizUserPasswordHistoryResponse,
    BizUserPasswordHistoryUpdateRequest,
    BizUserProfileCreateRequest,
    BizUserProfileListQuery,
    BizUserProfilePageResponse,
    BizUserProfileResponse,
    BizUserProfileUpdateRequest,
    BizUserResponse,
    BizUserSessionCreateRequest,
    BizUserSessionListQuery,
    BizUserSessionPageResponse,
    BizUserSessionResponse,
    BizUserSessionUpdateRequest,
    BizUserUpdateRequest,
    BizUserVerificationCreateRequest,
    BizUserVerificationListQuery,
    BizUserVerificationPageResponse,
    BizUserVerificationResponse,
    BizUserVerificationUpdateRequest,
)
from app.services.authorization import ApiPermissionCode

ROUTER = APIRouter()

_router_biz_user = APIRouter(prefix="/biz-user", tags=["biz_user"])


@_router_biz_user.get(
    "",
    summary="BizUser 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user",
            )
        ),
    ],
)
async def list_biz_user(
    query: Annotated[BizUserListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUser,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserPageResponse(
            list=[BizUserResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user.get(
    "/{entity_id}",
    summary="BizUser 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user",
            )
        ),
    ],
)
async def get_biz_user(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUser,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserResponse.model_validate(inst))


@_router_biz_user.post(
    "",
    summary="BizUser 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_CREATE,
                resource_type="biz_user",
            )
        ),
    ],
)
async def create_biz_user(
    payload: BizUserCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUser,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserResponse.model_validate(inst))


@_router_biz_user.put(
    "/{entity_id}",
    summary="BizUser 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_UPDATE,
                resource_type="biz_user",
            )
        ),
    ],
)
async def update_biz_user(
    entity_id: int,
    payload: BizUserUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUser,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserResponse.model_validate(inst))


@_router_biz_user.delete(
    "/{entity_id}",
    summary="BizUser 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_DELETE,
                resource_type="biz_user",
            )
        ),
    ],
)
async def delete_biz_user(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUser,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user)

_router_biz_user_level = APIRouter(prefix="/biz-user-level", tags=["biz_user"])


@_router_biz_user_level.get(
    "",
    summary="BizUserLevel 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_level",
            )
        ),
    ],
)
async def list_biz_user_level(
    query: Annotated[BizUserLevelListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevel,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_level",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserLevelPageResponse(
            list=[BizUserLevelResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_level.get(
    "/{entity_id}",
    summary="BizUserLevel 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_level",
            )
        ),
    ],
)
async def get_biz_user_level(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevel,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_level",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserLevelResponse.model_validate(inst))


@_router_biz_user_level.post(
    "",
    summary="BizUserLevel 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_CREATE,
                resource_type="biz_user_level",
            )
        ),
    ],
)
async def create_biz_user_level(
    payload: BizUserLevelCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevel,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_level",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserLevelResponse.model_validate(inst))


@_router_biz_user_level.put(
    "/{entity_id}",
    summary="BizUserLevel 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_UPDATE,
                resource_type="biz_user_level",
            )
        ),
    ],
)
async def update_biz_user_level(
    entity_id: int,
    payload: BizUserLevelUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevel,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_level",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserLevelResponse.model_validate(inst))


@_router_biz_user_level.delete(
    "/{entity_id}",
    summary="BizUserLevel 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_DELETE,
                resource_type="biz_user_level",
            )
        ),
    ],
)
async def delete_biz_user_level(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLevel,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_level",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserLevelResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_level)

_router_biz_user_login_identity = APIRouter(prefix="/biz-user-login-identity", tags=["biz_user"])


@_router_biz_user_login_identity.get(
    "",
    summary="BizUserLoginIdentity 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_login_identity",
            )
        ),
    ],
)
async def list_biz_user_login_identity(
    query: Annotated[BizUserLoginIdentityListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLoginIdentity,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_login_identity",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserLoginIdentityPageResponse(
            list=[BizUserLoginIdentityResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_login_identity.get(
    "/{entity_id}",
    summary="BizUserLoginIdentity 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_login_identity",
            )
        ),
    ],
)
async def get_biz_user_login_identity(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLoginIdentity,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_login_identity",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserLoginIdentityResponse.model_validate(inst))


@_router_biz_user_login_identity.post(
    "",
    summary="BizUserLoginIdentity 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_CREATE,
                resource_type="biz_user_login_identity",
            )
        ),
    ],
)
async def create_biz_user_login_identity(
    payload: BizUserLoginIdentityCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLoginIdentity,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_login_identity",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserLoginIdentityResponse.model_validate(inst))


@_router_biz_user_login_identity.put(
    "/{entity_id}",
    summary="BizUserLoginIdentity 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_UPDATE,
                resource_type="biz_user_login_identity",
            )
        ),
    ],
)
async def update_biz_user_login_identity(
    entity_id: int,
    payload: BizUserLoginIdentityUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLoginIdentity,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_login_identity",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserLoginIdentityResponse.model_validate(inst))


@_router_biz_user_login_identity.delete(
    "/{entity_id}",
    summary="BizUserLoginIdentity 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_DELETE,
                resource_type="biz_user_login_identity",
            )
        ),
    ],
)
async def delete_biz_user_login_identity(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLoginIdentity,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_login_identity",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserLoginIdentityResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_login_identity)

_router_biz_user_login_log = APIRouter(prefix="/biz-user-login-log", tags=["biz_user"])


@_router_biz_user_login_log.get(
    "",
    summary="BizUserLoginLog 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_login_log",
            )
        ),
    ],
)
async def list_biz_user_login_log(
    query: Annotated[BizUserLoginLogListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLoginLog,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_login_log",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserLoginLogPageResponse(
            list=[BizUserLoginLogResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_login_log.get(
    "/{entity_id}",
    summary="BizUserLoginLog 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_login_log",
            )
        ),
    ],
)
async def get_biz_user_login_log(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLoginLog,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_login_log",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserLoginLogResponse.model_validate(inst))


@_router_biz_user_login_log.post(
    "",
    summary="BizUserLoginLog 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_CREATE,
                resource_type="biz_user_login_log",
            )
        ),
    ],
)
async def create_biz_user_login_log(
    payload: BizUserLoginLogCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLoginLog,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_login_log",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserLoginLogResponse.model_validate(inst))


@_router_biz_user_login_log.put(
    "/{entity_id}",
    summary="BizUserLoginLog 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_UPDATE,
                resource_type="biz_user_login_log",
            )
        ),
    ],
)
async def update_biz_user_login_log(
    entity_id: int,
    payload: BizUserLoginLogUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLoginLog,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_login_log",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserLoginLogResponse.model_validate(inst))


@_router_biz_user_login_log.delete(
    "/{entity_id}",
    summary="BizUserLoginLog 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_DELETE,
                resource_type="biz_user_login_log",
            )
        ),
    ],
)
async def delete_biz_user_login_log(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserLoginLog,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_login_log",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserLoginLogResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_login_log)

_router_biz_user_password_history = APIRouter(
    prefix="/biz-user-password-history", tags=["biz_user"]
)


@_router_biz_user_password_history.get(
    "",
    summary="BizUserPasswordHistory 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_password_history",
            )
        ),
    ],
)
async def list_biz_user_password_history(
    query: Annotated[BizUserPasswordHistoryListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPasswordHistory,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_password_history",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserPasswordHistoryPageResponse(
            list=[BizUserPasswordHistoryResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_password_history.get(
    "/{entity_id}",
    summary="BizUserPasswordHistory 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_password_history",
            )
        ),
    ],
)
async def get_biz_user_password_history(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPasswordHistory,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_password_history",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserPasswordHistoryResponse.model_validate(inst))


@_router_biz_user_password_history.post(
    "",
    summary="BizUserPasswordHistory 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_CREATE,
                resource_type="biz_user_password_history",
            )
        ),
    ],
)
async def create_biz_user_password_history(
    payload: BizUserPasswordHistoryCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPasswordHistory,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_password_history",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserPasswordHistoryResponse.model_validate(inst))


@_router_biz_user_password_history.put(
    "/{entity_id}",
    summary="BizUserPasswordHistory 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_UPDATE,
                resource_type="biz_user_password_history",
            )
        ),
    ],
)
async def update_biz_user_password_history(
    entity_id: int,
    payload: BizUserPasswordHistoryUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPasswordHistory,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_password_history",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserPasswordHistoryResponse.model_validate(inst))


@_router_biz_user_password_history.delete(
    "/{entity_id}",
    summary="BizUserPasswordHistory 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_DELETE,
                resource_type="biz_user_password_history",
            )
        ),
    ],
)
async def delete_biz_user_password_history(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserPasswordHistory,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_password_history",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserPasswordHistoryResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_password_history)

_router_biz_user_profile = APIRouter(prefix="/biz-user-profile", tags=["biz_user"])


@_router_biz_user_profile.get(
    "",
    summary="BizUserProfile 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_profile",
            )
        ),
    ],
)
async def list_biz_user_profile(
    query: Annotated[BizUserProfileListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserProfile,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_profile",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserProfilePageResponse(
            list=[BizUserProfileResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_profile.get(
    "/{entity_id}",
    summary="BizUserProfile 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_profile",
            )
        ),
    ],
)
async def get_biz_user_profile(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserProfile,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_profile",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserProfileResponse.model_validate(inst))


@_router_biz_user_profile.post(
    "",
    summary="BizUserProfile 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_CREATE,
                resource_type="biz_user_profile",
            )
        ),
    ],
)
async def create_biz_user_profile(
    payload: BizUserProfileCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserProfile,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_profile",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserProfileResponse.model_validate(inst))


@_router_biz_user_profile.put(
    "/{entity_id}",
    summary="BizUserProfile 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_UPDATE,
                resource_type="biz_user_profile",
            )
        ),
    ],
)
async def update_biz_user_profile(
    entity_id: int,
    payload: BizUserProfileUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserProfile,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_profile",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserProfileResponse.model_validate(inst))


@_router_biz_user_profile.delete(
    "/{entity_id}",
    summary="BizUserProfile 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_DELETE,
                resource_type="biz_user_profile",
            )
        ),
    ],
)
async def delete_biz_user_profile(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserProfile,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_profile",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserProfileResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_profile)

_router_biz_user_session = APIRouter(prefix="/biz-user-session", tags=["biz_user"])


@_router_biz_user_session.get(
    "",
    summary="BizUserSession 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_session",
            )
        ),
    ],
)
async def list_biz_user_session(
    query: Annotated[BizUserSessionListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserSession,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_session",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserSessionPageResponse(
            list=[BizUserSessionResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_session.get(
    "/{entity_id}",
    summary="BizUserSession 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_session",
            )
        ),
    ],
)
async def get_biz_user_session(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserSession,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_session",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserSessionResponse.model_validate(inst))


@_router_biz_user_session.post(
    "",
    summary="BizUserSession 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_CREATE,
                resource_type="biz_user_session",
            )
        ),
    ],
)
async def create_biz_user_session(
    payload: BizUserSessionCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserSession,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_session",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserSessionResponse.model_validate(inst))


@_router_biz_user_session.put(
    "/{entity_id}",
    summary="BizUserSession 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_UPDATE,
                resource_type="biz_user_session",
            )
        ),
    ],
)
async def update_biz_user_session(
    entity_id: int,
    payload: BizUserSessionUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserSession,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_session",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserSessionResponse.model_validate(inst))


@_router_biz_user_session.delete(
    "/{entity_id}",
    summary="BizUserSession 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_DELETE,
                resource_type="biz_user_session",
            )
        ),
    ],
)
async def delete_biz_user_session(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserSession,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_session",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserSessionResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_session)

_router_biz_user_verification = APIRouter(prefix="/biz-user-verification", tags=["biz_user"])


@_router_biz_user_verification.get(
    "",
    summary="BizUserVerification 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_verification",
            )
        ),
    ],
)
async def list_biz_user_verification(
    query: Annotated[BizUserVerificationListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserVerification,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_verification",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BizUserVerificationPageResponse(
            list=[BizUserVerificationResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_biz_user_verification.get(
    "/{entity_id}",
    summary="BizUserVerification 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_READ,
                resource_type="biz_user_verification",
            )
        ),
    ],
)
async def get_biz_user_verification(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserVerification,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_verification",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BizUserVerificationResponse.model_validate(inst))


@_router_biz_user_verification.post(
    "",
    summary="BizUserVerification 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_CREATE,
                resource_type="biz_user_verification",
            )
        ),
    ],
)
async def create_biz_user_verification(
    payload: BizUserVerificationCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserVerification,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_verification",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BizUserVerificationResponse.model_validate(inst))


@_router_biz_user_verification.put(
    "/{entity_id}",
    summary="BizUserVerification 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_UPDATE,
                resource_type="biz_user_verification",
            )
        ),
    ],
)
async def update_biz_user_verification(
    entity_id: int,
    payload: BizUserVerificationUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserVerification,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_verification",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BizUserVerificationResponse.model_validate(inst))


@_router_biz_user_verification.delete(
    "/{entity_id}",
    summary="BizUserVerification 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BIZ_USER_MANAGE,
                action=AuditAction.BIZ_USER_DELETE,
                resource_type="biz_user_verification",
            )
        ),
    ],
)
async def delete_biz_user_verification(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BizUserVerification,
        permission_code=ApiPermissionCode.BIZ_USER_MANAGE,
        resource_type="biz_user_verification",
        audit_create=AuditAction.BIZ_USER_CREATE,
        audit_update=AuditAction.BIZ_USER_UPDATE,
        audit_delete=AuditAction.BIZ_USER_DELETE,
        audit_read=AuditAction.BIZ_USER_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BizUserVerificationResponse.model_validate(inst))


ROUTER.include_router(_router_biz_user_verification)


__all__ = [
    "ROUTER",
]
