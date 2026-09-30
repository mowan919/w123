# 05 Blog 博客域

## 1. blog_author

业务作者是 biz_user 的能力，不是独立登录用户。

```sql
CREATE TABLE blog_author (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE,
    author_name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    approved_at TIMESTAMPTZ,
    approved_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

`approved_by` 指向 `sys_user.id`。

## 2. blog_author_application

```sql
CREATE TABLE blog_author_application (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    application_reason VARCHAR(2000),
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    reviewed_by BIGINT,
    reviewed_at TIMESTAMPTZ,
    review_remark VARCHAR(1000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

状态：

```text
PENDING
APPROVED
REJECTED
```

## 3. blog_category

文章分类。

## 4. blog_article

核心字段：

```text
id
author_id
category_id
title
slug
summary
cover_url
content
status
published_at
view_count
like_count
favorite_count
comment_count
created_at
updated_at
deleted_at
```

文章状态建议：

```text
DRAFT
PENDING_REVIEW
REJECTED
PUBLISHED
OFFLINE
```

## 5. blog_article_version

保存文章编辑版本，便于审核和恢复。

## 6. blog_tag

```text
id
code
name
status
```

## 7. blog_article_tag

```text
article_id
tag_id
PRIMARY KEY(article_id, tag_id)
```

## 8. blog_comment

```text
id
article_id
user_id
parent_id
content
status
created_at
updated_at
deleted_at
```

## 9. blog_like

用户点赞唯一约束：

```text
UNIQUE(user_id, article_id)
```

## 10. blog_favorite

用户收藏唯一约束：

```text
UNIQUE(user_id, article_id)
```

## 11. blog_user_follow

```text
follower_user_id
followed_user_id
created_at
```

不能关注自己。

## 12. Blog 成长事件

可以产生：

```text
BLOG_ARTICLE_PUBLISHED
BLOG_COMMENT_CREATED
BLOG_LIKE_CREATED
BLOG_FAVORITE_CREATED
BLOG_FOLLOW_CREATED
```

最终由成长中心统一处理。
