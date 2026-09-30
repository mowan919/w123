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
from app.models.blog import (
    BlogArticle,
    BlogArticleTag,
    BlogArticleVersion,
    BlogAuthor,
    BlogAuthorApplication,
    BlogCategory,
    BlogComment,
    BlogFavorite,
    BlogLike,
    BlogTag,
    BlogUserFollow,
)
from app.schemas.v31_blog import (
    BlogArticleCreateRequest,
    BlogArticleListQuery,
    BlogArticlePageResponse,
    BlogArticleResponse,
    BlogArticleTagCreateRequest,
    BlogArticleTagListQuery,
    BlogArticleTagPageResponse,
    BlogArticleTagResponse,
    BlogArticleTagUpdateRequest,
    BlogArticleUpdateRequest,
    BlogArticleVersionCreateRequest,
    BlogArticleVersionListQuery,
    BlogArticleVersionPageResponse,
    BlogArticleVersionResponse,
    BlogArticleVersionUpdateRequest,
    BlogAuthorApplicationCreateRequest,
    BlogAuthorApplicationListQuery,
    BlogAuthorApplicationPageResponse,
    BlogAuthorApplicationResponse,
    BlogAuthorApplicationUpdateRequest,
    BlogAuthorCreateRequest,
    BlogAuthorListQuery,
    BlogAuthorPageResponse,
    BlogAuthorResponse,
    BlogAuthorUpdateRequest,
    BlogCategoryCreateRequest,
    BlogCategoryListQuery,
    BlogCategoryPageResponse,
    BlogCategoryResponse,
    BlogCategoryUpdateRequest,
    BlogCommentCreateRequest,
    BlogCommentListQuery,
    BlogCommentPageResponse,
    BlogCommentResponse,
    BlogCommentUpdateRequest,
    BlogFavoriteCreateRequest,
    BlogFavoriteListQuery,
    BlogFavoritePageResponse,
    BlogFavoriteResponse,
    BlogFavoriteUpdateRequest,
    BlogLikeCreateRequest,
    BlogLikeListQuery,
    BlogLikePageResponse,
    BlogLikeResponse,
    BlogLikeUpdateRequest,
    BlogTagCreateRequest,
    BlogTagListQuery,
    BlogTagPageResponse,
    BlogTagResponse,
    BlogTagUpdateRequest,
    BlogUserFollowCreateRequest,
    BlogUserFollowListQuery,
    BlogUserFollowPageResponse,
    BlogUserFollowResponse,
    BlogUserFollowUpdateRequest,
)
from app.services.authorization import ApiPermissionCode

ROUTER = APIRouter()

_router_blog_article = APIRouter(prefix="/blog-article", tags=["blog"])


@_router_blog_article.get(
    "",
    summary="BlogArticle 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_article",
            )
        ),
    ],
)
async def list_blog_article(
    query: Annotated[BlogArticleListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticle,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BlogArticlePageResponse(
            list=[BlogArticleResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_blog_article.get(
    "/{entity_id}",
    summary="BlogArticle 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_article",
            )
        ),
    ],
)
async def get_blog_article(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticle,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BlogArticleResponse.model_validate(inst))


@_router_blog_article.post(
    "",
    summary="BlogArticle 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_CREATE,
                resource_type="blog_article",
            )
        ),
    ],
)
async def create_blog_article(
    payload: BlogArticleCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticle,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BlogArticleResponse.model_validate(inst))


@_router_blog_article.put(
    "/{entity_id}",
    summary="BlogArticle 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_UPDATE,
                resource_type="blog_article",
            )
        ),
    ],
)
async def update_blog_article(
    entity_id: int,
    payload: BlogArticleUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticle,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BlogArticleResponse.model_validate(inst))


@_router_blog_article.delete(
    "/{entity_id}",
    summary="BlogArticle 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_DELETE,
                resource_type="blog_article",
            )
        ),
    ],
)
async def delete_blog_article(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticle,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BlogArticleResponse.model_validate(inst))


ROUTER.include_router(_router_blog_article)

_router_blog_article_tag = APIRouter(prefix="/blog-article-tag", tags=["blog"])


@_router_blog_article_tag.get(
    "",
    summary="BlogArticleTag 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_article_tag",
            )
        ),
    ],
)
async def list_blog_article_tag(
    query: Annotated[BlogArticleTagListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticleTag,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article_tag",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BlogArticleTagPageResponse(
            list=[BlogArticleTagResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_blog_article_tag.get(
    "/{entity_id}",
    summary="BlogArticleTag 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_article_tag",
            )
        ),
    ],
)
async def get_blog_article_tag(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticleTag,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article_tag",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BlogArticleTagResponse.model_validate(inst))


@_router_blog_article_tag.post(
    "",
    summary="BlogArticleTag 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_CREATE,
                resource_type="blog_article_tag",
            )
        ),
    ],
)
async def create_blog_article_tag(
    payload: BlogArticleTagCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticleTag,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article_tag",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BlogArticleTagResponse.model_validate(inst))


@_router_blog_article_tag.put(
    "/{entity_id}",
    summary="BlogArticleTag 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_UPDATE,
                resource_type="blog_article_tag",
            )
        ),
    ],
)
async def update_blog_article_tag(
    entity_id: int,
    payload: BlogArticleTagUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticleTag,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article_tag",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BlogArticleTagResponse.model_validate(inst))


@_router_blog_article_tag.delete(
    "/{entity_id}",
    summary="BlogArticleTag 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_DELETE,
                resource_type="blog_article_tag",
            )
        ),
    ],
)
async def delete_blog_article_tag(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticleTag,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article_tag",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BlogArticleTagResponse.model_validate(inst))


ROUTER.include_router(_router_blog_article_tag)

_router_blog_article_version = APIRouter(prefix="/blog-article-version", tags=["blog"])


@_router_blog_article_version.get(
    "",
    summary="BlogArticleVersion 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_article_version",
            )
        ),
    ],
)
async def list_blog_article_version(
    query: Annotated[BlogArticleVersionListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticleVersion,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article_version",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BlogArticleVersionPageResponse(
            list=[BlogArticleVersionResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_blog_article_version.get(
    "/{entity_id}",
    summary="BlogArticleVersion 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_article_version",
            )
        ),
    ],
)
async def get_blog_article_version(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticleVersion,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article_version",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BlogArticleVersionResponse.model_validate(inst))


@_router_blog_article_version.post(
    "",
    summary="BlogArticleVersion 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_CREATE,
                resource_type="blog_article_version",
            )
        ),
    ],
)
async def create_blog_article_version(
    payload: BlogArticleVersionCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticleVersion,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article_version",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BlogArticleVersionResponse.model_validate(inst))


@_router_blog_article_version.put(
    "/{entity_id}",
    summary="BlogArticleVersion 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_UPDATE,
                resource_type="blog_article_version",
            )
        ),
    ],
)
async def update_blog_article_version(
    entity_id: int,
    payload: BlogArticleVersionUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticleVersion,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article_version",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BlogArticleVersionResponse.model_validate(inst))


@_router_blog_article_version.delete(
    "/{entity_id}",
    summary="BlogArticleVersion 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_DELETE,
                resource_type="blog_article_version",
            )
        ),
    ],
)
async def delete_blog_article_version(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogArticleVersion,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_article_version",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BlogArticleVersionResponse.model_validate(inst))


ROUTER.include_router(_router_blog_article_version)

_router_blog_author = APIRouter(prefix="/blog-author", tags=["blog"])


@_router_blog_author.get(
    "",
    summary="BlogAuthor 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_author",
            )
        ),
    ],
)
async def list_blog_author(
    query: Annotated[BlogAuthorListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogAuthor,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_author",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BlogAuthorPageResponse(
            list=[BlogAuthorResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_blog_author.get(
    "/{entity_id}",
    summary="BlogAuthor 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_author",
            )
        ),
    ],
)
async def get_blog_author(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogAuthor,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_author",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BlogAuthorResponse.model_validate(inst))


@_router_blog_author.post(
    "",
    summary="BlogAuthor 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_CREATE,
                resource_type="blog_author",
            )
        ),
    ],
)
async def create_blog_author(
    payload: BlogAuthorCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogAuthor,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_author",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BlogAuthorResponse.model_validate(inst))


@_router_blog_author.put(
    "/{entity_id}",
    summary="BlogAuthor 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_UPDATE,
                resource_type="blog_author",
            )
        ),
    ],
)
async def update_blog_author(
    entity_id: int,
    payload: BlogAuthorUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogAuthor,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_author",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BlogAuthorResponse.model_validate(inst))


@_router_blog_author.delete(
    "/{entity_id}",
    summary="BlogAuthor 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_DELETE,
                resource_type="blog_author",
            )
        ),
    ],
)
async def delete_blog_author(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogAuthor,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_author",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BlogAuthorResponse.model_validate(inst))


ROUTER.include_router(_router_blog_author)

_router_blog_author_application = APIRouter(prefix="/blog-author-application", tags=["blog"])


@_router_blog_author_application.get(
    "",
    summary="BlogAuthorApplication 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_author_application",
            )
        ),
    ],
)
async def list_blog_author_application(
    query: Annotated[BlogAuthorApplicationListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogAuthorApplication,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_author_application",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BlogAuthorApplicationPageResponse(
            list=[BlogAuthorApplicationResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_blog_author_application.get(
    "/{entity_id}",
    summary="BlogAuthorApplication 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_author_application",
            )
        ),
    ],
)
async def get_blog_author_application(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogAuthorApplication,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_author_application",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BlogAuthorApplicationResponse.model_validate(inst))


@_router_blog_author_application.post(
    "",
    summary="BlogAuthorApplication 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_CREATE,
                resource_type="blog_author_application",
            )
        ),
    ],
)
async def create_blog_author_application(
    payload: BlogAuthorApplicationCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogAuthorApplication,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_author_application",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BlogAuthorApplicationResponse.model_validate(inst))


@_router_blog_author_application.put(
    "/{entity_id}",
    summary="BlogAuthorApplication 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_UPDATE,
                resource_type="blog_author_application",
            )
        ),
    ],
)
async def update_blog_author_application(
    entity_id: int,
    payload: BlogAuthorApplicationUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogAuthorApplication,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_author_application",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BlogAuthorApplicationResponse.model_validate(inst))


@_router_blog_author_application.delete(
    "/{entity_id}",
    summary="BlogAuthorApplication 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_DELETE,
                resource_type="blog_author_application",
            )
        ),
    ],
)
async def delete_blog_author_application(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogAuthorApplication,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_author_application",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BlogAuthorApplicationResponse.model_validate(inst))


ROUTER.include_router(_router_blog_author_application)

_router_blog_category = APIRouter(prefix="/blog-category", tags=["blog"])


@_router_blog_category.get(
    "",
    summary="BlogCategory 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_category",
            )
        ),
    ],
)
async def list_blog_category(
    query: Annotated[BlogCategoryListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogCategory,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_category",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BlogCategoryPageResponse(
            list=[BlogCategoryResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_blog_category.get(
    "/{entity_id}",
    summary="BlogCategory 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_category",
            )
        ),
    ],
)
async def get_blog_category(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogCategory,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_category",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BlogCategoryResponse.model_validate(inst))


@_router_blog_category.post(
    "",
    summary="BlogCategory 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_CREATE,
                resource_type="blog_category",
            )
        ),
    ],
)
async def create_blog_category(
    payload: BlogCategoryCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogCategory,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_category",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BlogCategoryResponse.model_validate(inst))


@_router_blog_category.put(
    "/{entity_id}",
    summary="BlogCategory 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_UPDATE,
                resource_type="blog_category",
            )
        ),
    ],
)
async def update_blog_category(
    entity_id: int,
    payload: BlogCategoryUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogCategory,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_category",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BlogCategoryResponse.model_validate(inst))


@_router_blog_category.delete(
    "/{entity_id}",
    summary="BlogCategory 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_DELETE,
                resource_type="blog_category",
            )
        ),
    ],
)
async def delete_blog_category(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogCategory,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_category",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BlogCategoryResponse.model_validate(inst))


ROUTER.include_router(_router_blog_category)

_router_blog_comment = APIRouter(prefix="/blog-comment", tags=["blog"])


@_router_blog_comment.get(
    "",
    summary="BlogComment 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_comment",
            )
        ),
    ],
)
async def list_blog_comment(
    query: Annotated[BlogCommentListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogComment,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_comment",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BlogCommentPageResponse(
            list=[BlogCommentResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_blog_comment.get(
    "/{entity_id}",
    summary="BlogComment 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_comment",
            )
        ),
    ],
)
async def get_blog_comment(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogComment,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_comment",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BlogCommentResponse.model_validate(inst))


@_router_blog_comment.post(
    "",
    summary="BlogComment 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_CREATE,
                resource_type="blog_comment",
            )
        ),
    ],
)
async def create_blog_comment(
    payload: BlogCommentCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogComment,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_comment",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BlogCommentResponse.model_validate(inst))


@_router_blog_comment.put(
    "/{entity_id}",
    summary="BlogComment 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_UPDATE,
                resource_type="blog_comment",
            )
        ),
    ],
)
async def update_blog_comment(
    entity_id: int,
    payload: BlogCommentUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogComment,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_comment",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BlogCommentResponse.model_validate(inst))


@_router_blog_comment.delete(
    "/{entity_id}",
    summary="BlogComment 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_DELETE,
                resource_type="blog_comment",
            )
        ),
    ],
)
async def delete_blog_comment(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogComment,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_comment",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BlogCommentResponse.model_validate(inst))


ROUTER.include_router(_router_blog_comment)

_router_blog_favorite = APIRouter(prefix="/blog-favorite", tags=["blog"])


@_router_blog_favorite.get(
    "",
    summary="BlogFavorite 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_favorite",
            )
        ),
    ],
)
async def list_blog_favorite(
    query: Annotated[BlogFavoriteListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogFavorite,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_favorite",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BlogFavoritePageResponse(
            list=[BlogFavoriteResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_blog_favorite.get(
    "/{entity_id}",
    summary="BlogFavorite 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_favorite",
            )
        ),
    ],
)
async def get_blog_favorite(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogFavorite,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_favorite",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BlogFavoriteResponse.model_validate(inst))


@_router_blog_favorite.post(
    "",
    summary="BlogFavorite 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_CREATE,
                resource_type="blog_favorite",
            )
        ),
    ],
)
async def create_blog_favorite(
    payload: BlogFavoriteCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogFavorite,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_favorite",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BlogFavoriteResponse.model_validate(inst))


@_router_blog_favorite.put(
    "/{entity_id}",
    summary="BlogFavorite 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_UPDATE,
                resource_type="blog_favorite",
            )
        ),
    ],
)
async def update_blog_favorite(
    entity_id: int,
    payload: BlogFavoriteUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogFavorite,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_favorite",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BlogFavoriteResponse.model_validate(inst))


@_router_blog_favorite.delete(
    "/{entity_id}",
    summary="BlogFavorite 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_DELETE,
                resource_type="blog_favorite",
            )
        ),
    ],
)
async def delete_blog_favorite(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogFavorite,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_favorite",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BlogFavoriteResponse.model_validate(inst))


ROUTER.include_router(_router_blog_favorite)

_router_blog_like = APIRouter(prefix="/blog-like", tags=["blog"])


@_router_blog_like.get(
    "",
    summary="BlogLike 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_like",
            )
        ),
    ],
)
async def list_blog_like(
    query: Annotated[BlogLikeListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogLike,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_like",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BlogLikePageResponse(
            list=[BlogLikeResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_blog_like.get(
    "/{entity_id}",
    summary="BlogLike 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_like",
            )
        ),
    ],
)
async def get_blog_like(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogLike,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_like",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BlogLikeResponse.model_validate(inst))


@_router_blog_like.post(
    "",
    summary="BlogLike 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_CREATE,
                resource_type="blog_like",
            )
        ),
    ],
)
async def create_blog_like(
    payload: BlogLikeCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogLike,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_like",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BlogLikeResponse.model_validate(inst))


@_router_blog_like.put(
    "/{entity_id}",
    summary="BlogLike 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_UPDATE,
                resource_type="blog_like",
            )
        ),
    ],
)
async def update_blog_like(
    entity_id: int,
    payload: BlogLikeUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogLike,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_like",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BlogLikeResponse.model_validate(inst))


@_router_blog_like.delete(
    "/{entity_id}",
    summary="BlogLike 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_DELETE,
                resource_type="blog_like",
            )
        ),
    ],
)
async def delete_blog_like(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogLike,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_like",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BlogLikeResponse.model_validate(inst))


ROUTER.include_router(_router_blog_like)

_router_blog_tag = APIRouter(prefix="/blog-tag", tags=["blog"])


@_router_blog_tag.get(
    "",
    summary="BlogTag 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_tag",
            )
        ),
    ],
)
async def list_blog_tag(
    query: Annotated[BlogTagListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogTag,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_tag",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BlogTagPageResponse(
            list=[BlogTagResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_blog_tag.get(
    "/{entity_id}",
    summary="BlogTag 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_tag",
            )
        ),
    ],
)
async def get_blog_tag(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogTag,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_tag",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BlogTagResponse.model_validate(inst))


@_router_blog_tag.post(
    "",
    summary="BlogTag 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_CREATE,
                resource_type="blog_tag",
            )
        ),
    ],
)
async def create_blog_tag(
    payload: BlogTagCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogTag,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_tag",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BlogTagResponse.model_validate(inst))


@_router_blog_tag.put(
    "/{entity_id}",
    summary="BlogTag 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_UPDATE,
                resource_type="blog_tag",
            )
        ),
    ],
)
async def update_blog_tag(
    entity_id: int,
    payload: BlogTagUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogTag,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_tag",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BlogTagResponse.model_validate(inst))


@_router_blog_tag.delete(
    "/{entity_id}",
    summary="BlogTag 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_DELETE,
                resource_type="blog_tag",
            )
        ),
    ],
)
async def delete_blog_tag(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogTag,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_tag",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BlogTagResponse.model_validate(inst))


ROUTER.include_router(_router_blog_tag)

_router_blog_user_follow = APIRouter(prefix="/blog-user-follow", tags=["blog"])


@_router_blog_user_follow.get(
    "",
    summary="BlogUserFollow 列表",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_user_follow",
            )
        ),
    ],
)
async def list_blog_user_follow(
    query: Annotated[BlogUserFollowListQuery, Query()],
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogUserFollow,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_user_follow",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    page = await svc.list(
        actor=actor,
        filters=query.filters(),
        page_num=query.pageNum,
        page_size=query.pageSize,
    )
    return success_response(
        BlogUserFollowPageResponse(
            list=[BlogUserFollowResponse.model_validate(i) for i in page.items],
            total=page.total,
            pageNum=page.page_num,
            pageSize=page.page_size,
        )
    )


@_router_blog_user_follow.get(
    "/{entity_id}",
    summary="BlogUserFollow 详情",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_READ,
                resource_type="blog_user_follow",
            )
        ),
    ],
)
async def get_blog_user_follow(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogUserFollow,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_user_follow",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.get(actor=actor, entity_id=entity_id)
    return success_response(BlogUserFollowResponse.model_validate(inst))


@_router_blog_user_follow.post(
    "",
    summary="BlogUserFollow 创建",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_CREATE,
                resource_type="blog_user_follow",
            )
        ),
    ],
)
async def create_blog_user_follow(
    payload: BlogUserFollowCreateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogUserFollow,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_user_follow",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.create(actor=actor, fields=payload.model_dump())
    await session.commit()
    return success_response(BlogUserFollowResponse.model_validate(inst))


@_router_blog_user_follow.put(
    "/{entity_id}",
    summary="BlogUserFollow 更新",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_UPDATE,
                resource_type="blog_user_follow",
            )
        ),
    ],
)
async def update_blog_user_follow(
    entity_id: int,
    payload: BlogUserFollowUpdateRequest,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogUserFollow,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_user_follow",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.update(
        actor=actor,
        entity_id=entity_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return success_response(BlogUserFollowResponse.model_validate(inst))


@_router_blog_user_follow.delete(
    "/{entity_id}",
    summary="BlogUserFollow 删除",
    dependencies=[
        Depends(
            require_api_permission(
                ApiPermissionCode.BLOG_MANAGE,
                action=AuditAction.BLOG_DELETE,
                resource_type="blog_user_follow",
            )
        ),
    ],
)
async def delete_blog_user_follow(
    entity_id: int,
    actor: CurrentActorDep,
    session: DbSessionDep,
) -> JSONResponse:
    svc = BaseCrudService(
        session,
        audit=BufferingAuditRecorder(),
        model_cls=BlogUserFollow,
        permission_code=ApiPermissionCode.BLOG_MANAGE,
        resource_type="blog_user_follow",
        audit_create=AuditAction.BLOG_CREATE,
        audit_update=AuditAction.BLOG_UPDATE,
        audit_delete=AuditAction.BLOG_DELETE,
        audit_read=AuditAction.BLOG_READ,
    )
    inst = await svc.delete(actor=actor, entity_id=entity_id)
    await session.commit()
    return success_response(BlogUserFollowResponse.model_validate(inst))


ROUTER.include_router(_router_blog_user_follow)


__all__ = [
    "ROUTER",
]
