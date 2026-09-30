"""Blog 博客域模型 —— V3.1 数据库设计基线（`05 Blog 博客域` + `08-DDL基线.sql`）。

Frozen 依据
-----------
- `08-DDL基线.sql` 的 Blog 段落是结构基线，本文件严格按基线落库。
- `05 §1`：业务作者是 `biz_user` 的能力，不是独立登录用户
  （`blog_author.user_id` 指向 `biz_user.id`，与系统管理员 `admin_users` 分离）。
- `05 §1`：`blog_author.approved_by` 指向 `admin_users.id`（系统管理员审核）。

状态 / 类型列说明
----------------
- `article.status`（`05 §4` 显式 DRAFT/PENDING_REVIEW/REJECTED/PUBLISHED/OFFLINE）、
  `application.status`（PENDING/APPROVED/REJECTED）以枚举列落库
  （`app/models/enums.py`）。
- `author.status` / `comment.status` / `tag.status` / 各类通用 status 仅给
  DEFAULT、未枚举取值域，以普通 VARCHAR 落库，取值域待冻结。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TimestampMixin, utc_now
from app.db.types import enum_type
from app.models.enums import BlogArticleStatus, BlogAuthorApplicationStatus


class BlogAuthor(PrimaryKeyMixin, TimestampMixin, Base):
    """博客作者（`08-DDL基线.sql` / `05 §1`）。

    业务作者 = biz_user 的能力；user_id 唯一。approved_by 指向审核的管理员。
    """

    __tablename__ = "blog_author"

    user_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, comment="业务用户 ID（唯一）"
    )
    author_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="作者名")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="审核通过时间 (UTC)"
    )
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="审核人（管理员）ID",
    )


class BlogAuthorApplication(PrimaryKeyMixin, TimestampMixin, Base):
    """博客作者申请（`08-DDL基线.sql` / `05 §2`）。"""

    __tablename__ = "blog_author_application"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        nullable=False,
        comment="申请人（业务用户）ID",
    )
    application_reason: Mapped[str | None] = mapped_column(
        String(2000), nullable=True, comment="申请理由"
    )
    status: Mapped[BlogAuthorApplicationStatus] = mapped_column(
        enum_type(BlogAuthorApplicationStatus, name="status"),
        nullable=False,
        default=BlogAuthorApplicationStatus.PENDING,
        comment="申请状态 PENDING / APPROVED / REJECTED",
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="审核人（管理员）ID",
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="审核时间 (UTC)"
    )
    review_remark: Mapped[str | None] = mapped_column(
        String(1000), nullable=True, comment="审核备注"
    )


class BlogCategory(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """博客文章分类（`08-DDL基线.sql` / `05 §3`）。"""

    __tablename__ = "blog_category"

    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("blog_category.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="父分类 ID；NULL 表示根分类",
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="分类编码；唯一")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="分类名称")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )

    __table_args__ = (
        Index(
            "uq_blog_category_code_active",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class BlogArticle(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """博客文章（`08-DDL基线.sql` / `05 §4`）。"""

    __tablename__ = "blog_article"

    author_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("blog_author.id", ondelete="RESTRICT"),
        nullable=False,
        comment="作者 ID",
    )
    category_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("blog_category.id", ondelete="RESTRICT"),
        nullable=True,
        comment="分类 ID",
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="标题")
    slug: Mapped[str] = mapped_column(String(255), nullable=False, comment="URL 别名；唯一")
    summary: Mapped[str | None] = mapped_column(String(1000), nullable=True, comment="摘要")
    cover_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="封面 URL")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="正文")
    status: Mapped[BlogArticleStatus] = mapped_column(
        enum_type(BlogArticleStatus, name="status"),
        nullable=False,
        default=BlogArticleStatus.DRAFT,
        comment="文章状态 DRAFT/PENDING_REVIEW/REJECTED/PUBLISHED/OFFLINE",
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="发布时间 (UTC)"
    )
    view_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="浏览数")
    like_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="点赞数")
    favorite_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="收藏数"
    )
    comment_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="评论数"
    )

    __table_args__ = (
        Index(
            "uq_blog_article_slug_active",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_blog_article_author_status", "author_id", "status"),
    )


class BlogArticleVersion(PrimaryKeyMixin, Base):
    """博客文章版本（`08-DDL基线.sql` / `05 §5`：保存编辑版本便于审核与恢复）。

    只有 created_at、无 updated_at（版本不可变）。
    """

    __tablename__ = "blog_article_version"

    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("blog_article.id", ondelete="RESTRICT"),
        nullable=False,
        comment="文章 ID",
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="标题")
    summary: Mapped[str | None] = mapped_column(String(1000), nullable=True, comment="摘要")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="正文")
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="创建人（管理员）ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )

    __table_args__ = (
        UniqueConstraint("article_id", "version_no", name="uq_blog_article_version_no"),
    )


class BlogTag(PrimaryKeyMixin, Base):
    """博客标签（`08-DDL基线.sql` / `05 §6`）。

    只有 created_at、无 updated_at。
    """

    __tablename__ = "blog_tag"

    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="标签编码；唯一")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="标签名称")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ACTIVE", comment="状态；取值域待冻结"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )

    __table_args__ = (UniqueConstraint("code", name="uq_blog_tag_code"),)


class BlogArticleTag(Base):
    """文章-标签关联（`08-DDL基线.sql` / `05 §7`）。"""

    __tablename__ = "blog_article_tag"

    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("blog_article.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
        comment="文章 ID",
    )
    tag_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("blog_tag.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
        comment="标签 ID",
    )


class BlogComment(PrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """博客评论（`08-DDL基线.sql` / `05 §8`）。"""

    __tablename__ = "blog_comment"

    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("blog_article.id", ondelete="RESTRICT"),
        nullable=False,
        comment="文章 ID",
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        nullable=False,
        comment="评论用户（业务用户）ID",
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("blog_comment.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="父评论 ID；NULL 表示顶层评论",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="评论内容")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="PUBLISHED", comment="状态；取值域待冻结"
    )

    __table_args__ = (Index("ix_blog_comment_article_time", "article_id", text("created_at DESC")),)


class BlogLike(PrimaryKeyMixin, Base):
    """博客点赞（`08-DDL基线.sql` / `05 §9`：用户点赞唯一约束）。"""

    __tablename__ = "blog_like"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
        comment="业务用户 ID",
    )
    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("blog_article.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
        comment="文章 ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )


class BlogFavorite(PrimaryKeyMixin, Base):
    """博客收藏（`08-DDL基线.sql` / `05 §10`：用户收藏唯一约束）。"""

    __tablename__ = "blog_favorite"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
        comment="业务用户 ID",
    )
    article_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("blog_article.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
        comment="文章 ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )


class BlogUserFollow(PrimaryKeyMixin, Base):
    """用户关注（`08-DDL基线.sql` / `05 §11`：不能关注自己）。"""

    __tablename__ = "blog_user_follow"

    follower_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
        comment="关注者（业务用户）ID",
    )
    followed_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("biz_user.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
        comment="被关注者（业务用户）ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, comment="创建时间 (UTC)"
    )

    __table_args__ = (
        CheckConstraint("follower_user_id <> followed_user_id", name="follower_not_self"),
    )


__all__ = [
    "BlogArticle",
    "BlogArticleTag",
    "BlogArticleVersion",
    "BlogAuthor",
    "BlogAuthorApplication",
    "BlogCategory",
    "BlogComment",
    "BlogFavorite",
    "BlogLike",
    "BlogTag",
    "BlogUserFollow",
]
