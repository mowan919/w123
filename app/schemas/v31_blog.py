"""V3.1 结构层 CRUD 契约（VCTN §33，自动生成）。

本文件由 `scripts/gen_v31_crud.py` 生成；业务规则（§09-D 未冻结项）不在此处。
"""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import BlogArticleStatus, BlogAuthorApplicationStatus
from app.schemas.types import SnowflakeId


class BlogArticleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    author_id: SnowflakeId
    category_id: SnowflakeId
    title: str
    slug: str
    summary: str | None
    cover_url: str | None
    content: str
    status: BlogArticleStatus
    published_at: datetime | None
    view_count: int
    like_count: int
    favorite_count: int
    comment_count: int
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class BlogArticleListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    author_id: SnowflakeId | None = Field(default=None)
    category_id: SnowflakeId | None = Field(default=None)
    status: BlogArticleStatus | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BlogArticleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    author_id: SnowflakeId = Field()
    category_id: SnowflakeId | None = Field(default=None)
    title: str = Field(max_length=255)
    slug: str = Field(max_length=255)
    summary: str | None = Field(default=None)
    cover_url: str | None = Field(default=None)
    content: str = Field()
    status: BlogArticleStatus | None = Field(default=None)
    published_at: datetime | None = Field(default=None)
    view_count: int | None = Field(default=None)
    like_count: int | None = Field(default=None)
    favorite_count: int | None = Field(default=None)
    comment_count: int | None = Field(default=None)


class BlogArticleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    author_id: SnowflakeId | None = Field(default=None)
    category_id: SnowflakeId | None = Field(default=None)
    title: str | None = Field(default=None)
    slug: str | None = Field(default=None)
    summary: str | None = Field(default=None)
    cover_url: str | None = Field(default=None)
    content: str | None = Field(default=None)
    status: BlogArticleStatus | None = Field(default=None)
    published_at: datetime | None = Field(default=None)
    view_count: int | None = Field(default=None)
    like_count: int | None = Field(default=None)
    favorite_count: int | None = Field(default=None)
    comment_count: int | None = Field(default=None)


class BlogArticlePageResponse(BaseModel):
    list: builtins.list[BlogArticleResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BlogArticleTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    article_id: SnowflakeId
    tag_id: SnowflakeId


class BlogArticleTagListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    article_id: SnowflakeId | None = Field(default=None)
    tag_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BlogArticleTagCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: SnowflakeId = Field()
    tag_id: SnowflakeId = Field()


class BlogArticleTagUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: SnowflakeId | None = Field(default=None)
    tag_id: SnowflakeId | None = Field(default=None)


class BlogArticleTagPageResponse(BaseModel):
    list: builtins.list[BlogArticleTagResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BlogArticleVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    article_id: SnowflakeId
    version_no: int
    title: str
    summary: str | None
    content: str
    created_by: SnowflakeId
    created_at: datetime
    id: int


class BlogArticleVersionListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    article_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BlogArticleVersionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: SnowflakeId = Field()
    version_no: int = Field()
    title: str = Field(max_length=255)
    summary: str | None = Field(default=None)
    content: str = Field()


class BlogArticleVersionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: SnowflakeId | None = Field(default=None)
    version_no: int | None = Field(default=None)
    title: str | None = Field(default=None)
    summary: str | None = Field(default=None)
    content: str | None = Field(default=None)


class BlogArticleVersionPageResponse(BaseModel):
    list: builtins.list[BlogArticleVersionResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BlogAuthorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    author_name: str
    status: str
    approved_at: datetime | None
    approved_by: SnowflakeId
    id: int
    created_at: datetime
    updated_at: datetime


class BlogAuthorListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    status: str | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BlogAuthorCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field()
    author_name: str = Field(max_length=128)
    status: str | None = Field(default=None)
    approved_at: datetime | None = Field(default=None)


class BlogAuthorUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int | None = Field(default=None)
    author_name: str | None = Field(default=None)
    status: str | None = Field(default=None)
    approved_at: datetime | None = Field(default=None)


class BlogAuthorPageResponse(BaseModel):
    list: builtins.list[BlogAuthorResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BlogAuthorApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: SnowflakeId
    application_reason: str | None
    status: BlogAuthorApplicationStatus
    reviewed_by: SnowflakeId
    reviewed_at: datetime | None
    review_remark: str | None
    id: int
    created_at: datetime
    updated_at: datetime


class BlogAuthorApplicationListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    user_id: SnowflakeId | None = Field(default=None)
    status: BlogAuthorApplicationStatus | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BlogAuthorApplicationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId = Field()
    application_reason: str | None = Field(default=None)
    status: BlogAuthorApplicationStatus | None = Field(default=None)
    reviewed_at: datetime | None = Field(default=None)
    review_remark: str | None = Field(default=None)


class BlogAuthorApplicationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId | None = Field(default=None)
    application_reason: str | None = Field(default=None)
    status: BlogAuthorApplicationStatus | None = Field(default=None)
    reviewed_at: datetime | None = Field(default=None)
    review_remark: str | None = Field(default=None)


class BlogAuthorApplicationPageResponse(BaseModel):
    list: builtins.list[BlogAuthorApplicationResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BlogCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    parent_id: SnowflakeId
    code: str
    name: str
    sort_order: int
    status: str
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class BlogCategoryListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    parent_id: SnowflakeId | None = Field(default=None)
    code: str | None = Field(default=None)
    status: str | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BlogCategoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: SnowflakeId | None = Field(default=None)
    code: str = Field(max_length=64)
    name: str = Field(max_length=128)
    sort_order: int | None = Field(default=None)
    status: str | None = Field(default=None)


class BlogCategoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: SnowflakeId | None = Field(default=None)
    code: str | None = Field(default=None)
    name: str | None = Field(default=None)
    sort_order: int | None = Field(default=None)
    status: str | None = Field(default=None)


class BlogCategoryPageResponse(BaseModel):
    list: builtins.list[BlogCategoryResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BlogCommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    article_id: SnowflakeId
    user_id: SnowflakeId
    parent_id: SnowflakeId
    content: str
    status: str
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class BlogCommentListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    article_id: SnowflakeId | None = Field(default=None)
    user_id: SnowflakeId | None = Field(default=None)
    parent_id: SnowflakeId | None = Field(default=None)
    status: str | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BlogCommentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: SnowflakeId = Field()
    user_id: SnowflakeId = Field()
    parent_id: SnowflakeId | None = Field(default=None)
    content: str = Field()
    status: str | None = Field(default=None)


class BlogCommentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: SnowflakeId | None = Field(default=None)
    user_id: SnowflakeId | None = Field(default=None)
    parent_id: SnowflakeId | None = Field(default=None)
    content: str | None = Field(default=None)
    status: str | None = Field(default=None)


class BlogCommentPageResponse(BaseModel):
    list: builtins.list[BlogCommentResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BlogFavoriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: SnowflakeId
    article_id: SnowflakeId
    created_at: datetime
    id: int


class BlogFavoriteListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    user_id: SnowflakeId | None = Field(default=None)
    article_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BlogFavoriteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId = Field()
    article_id: SnowflakeId = Field()


class BlogFavoriteUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId | None = Field(default=None)
    article_id: SnowflakeId | None = Field(default=None)


class BlogFavoritePageResponse(BaseModel):
    list: builtins.list[BlogFavoriteResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BlogLikeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: SnowflakeId
    article_id: SnowflakeId
    created_at: datetime
    id: int


class BlogLikeListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    user_id: SnowflakeId | None = Field(default=None)
    article_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BlogLikeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId = Field()
    article_id: SnowflakeId = Field()


class BlogLikeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: SnowflakeId | None = Field(default=None)
    article_id: SnowflakeId | None = Field(default=None)


class BlogLikePageResponse(BaseModel):
    list: builtins.list[BlogLikeResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BlogTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    status: str
    created_at: datetime
    id: int


class BlogTagListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    code: str | None = Field(default=None)
    status: str | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BlogTagCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=64)
    name: str = Field(max_length=128)
    status: str | None = Field(default=None)


class BlogTagUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str | None = Field(default=None)
    name: str | None = Field(default=None)
    status: str | None = Field(default=None)


class BlogTagPageResponse(BaseModel):
    list: builtins.list[BlogTagResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


class BlogUserFollowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    follower_user_id: SnowflakeId
    followed_user_id: SnowflakeId
    created_at: datetime
    id: int


class BlogUserFollowListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    follower_user_id: SnowflakeId | None = Field(default=None)
    followed_user_id: SnowflakeId | None = Field(default=None)

    def filters(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("pageNum", None)
        data.pop("pageSize", None)
        return {k: v for k, v in data.items() if v is not None}


class BlogUserFollowCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    follower_user_id: SnowflakeId = Field()
    followed_user_id: SnowflakeId = Field()


class BlogUserFollowUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    follower_user_id: SnowflakeId | None = Field(default=None)
    followed_user_id: SnowflakeId | None = Field(default=None)


class BlogUserFollowPageResponse(BaseModel):
    list: builtins.list[BlogUserFollowResponse] = Field(default_factory=builtins.list)
    total: int
    pageNum: int
    pageSize: int


__all__ = [
    "BlogArticleCreateRequest",
    "BlogArticleListQuery",
    "BlogArticlePageResponse",
    "BlogArticleResponse",
    "BlogArticleTagCreateRequest",
    "BlogArticleTagListQuery",
    "BlogArticleTagPageResponse",
    "BlogArticleTagResponse",
    "BlogArticleTagUpdateRequest",
    "BlogArticleUpdateRequest",
    "BlogArticleVersionCreateRequest",
    "BlogArticleVersionListQuery",
    "BlogArticleVersionPageResponse",
    "BlogArticleVersionResponse",
    "BlogArticleVersionUpdateRequest",
    "BlogAuthorApplicationCreateRequest",
    "BlogAuthorApplicationListQuery",
    "BlogAuthorApplicationPageResponse",
    "BlogAuthorApplicationResponse",
    "BlogAuthorApplicationUpdateRequest",
    "BlogAuthorCreateRequest",
    "BlogAuthorListQuery",
    "BlogAuthorPageResponse",
    "BlogAuthorResponse",
    "BlogAuthorUpdateRequest",
    "BlogCategoryCreateRequest",
    "BlogCategoryListQuery",
    "BlogCategoryPageResponse",
    "BlogCategoryResponse",
    "BlogCategoryUpdateRequest",
    "BlogCommentCreateRequest",
    "BlogCommentListQuery",
    "BlogCommentPageResponse",
    "BlogCommentResponse",
    "BlogCommentUpdateRequest",
    "BlogFavoriteCreateRequest",
    "BlogFavoriteListQuery",
    "BlogFavoritePageResponse",
    "BlogFavoriteResponse",
    "BlogFavoriteUpdateRequest",
    "BlogLikeCreateRequest",
    "BlogLikeListQuery",
    "BlogLikePageResponse",
    "BlogLikeResponse",
    "BlogLikeUpdateRequest",
    "BlogTagCreateRequest",
    "BlogTagListQuery",
    "BlogTagPageResponse",
    "BlogTagResponse",
    "BlogTagUpdateRequest",
    "BlogUserFollowCreateRequest",
    "BlogUserFollowListQuery",
    "BlogUserFollowPageResponse",
    "BlogUserFollowResponse",
    "BlogUserFollowUpdateRequest",
]
