-- VCTN Database DDL Baseline V3.1
-- PostgreSQL
-- 注意：本文件是结构基线；最终 Alembic migration 必须按项目冻结决策拆分。

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =========================
-- System
-- =========================

CREATE TABLE IF NOT EXISTS sys_department (
    id BIGINT PRIMARY KEY,
    parent_id BIGINT,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sys_user (
    id BIGINT PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    real_name VARCHAR(128),
    phone VARCHAR(32),
    email VARCHAR(255),
    department_id BIGINT,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
    password_changed_at TIMESTAMPTZ,
    password_expires_at TIMESTAMPTZ,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    last_login_ip INET,
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sys_user_username_active
ON sys_user(username) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS sys_role (
    id BIGINT PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    description VARCHAR(500),
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sys_user_role (
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, role_id)
);

CREATE TABLE IF NOT EXISTS sys_role_inheritance (
    parent_role_id BIGINT NOT NULL,
    child_role_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(parent_role_id, child_role_id),
    CHECK(parent_role_id <> child_role_id)
);

CREATE TABLE IF NOT EXISTS sys_permission (
    id BIGINT PRIMARY KEY,
    parent_id BIGINT,
    resource_type VARCHAR(32) NOT NULL,
    resource_code VARCHAR(255) NOT NULL UNIQUE,
    resource_name VARCHAR(255) NOT NULL,
    path VARCHAR(500),
    method VARCHAR(16),
    field_name VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    sort_order INTEGER NOT NULL DEFAULT 0,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sys_role_permission (
    role_id BIGINT NOT NULL,
    permission_id BIGINT NOT NULL,
    field_mode VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS sys_session (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    session_id VARCHAR(128) NOT NULL UNIQUE,
    token_version BIGINT NOT NULL DEFAULT 1,
    ip INET,
    user_agent VARCHAR(1000),
    login_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    revoke_reason VARCHAR(255)
);

-- =========================
-- Business User
-- =========================

CREATE TABLE IF NOT EXISTS biz_user_level (
    id BIGINT PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    level_value INTEGER NOT NULL UNIQUE,
    required_growth_points BIGINT NOT NULL,
    icon_url VARCHAR(512),
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    sort_order INTEGER NOT NULL DEFAULT 0,
    description VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS biz_user (
    id BIGINT PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    user_level_id BIGINT,
    must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
    password_changed_at TIMESTAMPTZ,
    password_expires_at TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    last_login_ip INET,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_biz_user_username_active
ON biz_user(username) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS biz_user_profile (
    user_id BIGINT PRIMARY KEY,
    nickname VARCHAR(128),
    avatar_url VARCHAR(512),
    bio VARCHAR(1000),
    gender VARCHAR(32),
    birthday DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS biz_user_login_identity (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    identity_type VARCHAR(32) NOT NULL,
    normalized_value VARCHAR(255) NOT NULL,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(identity_type, normalized_value)
);

CREATE TABLE IF NOT EXISTS biz_user_session (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    session_id VARCHAR(128) NOT NULL UNIQUE,
    ip INET,
    user_agent VARCHAR(1000),
    login_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    revoke_reason VARCHAR(255)
);

-- =========================
-- Growth
-- =========================

CREATE TABLE IF NOT EXISTS biz_user_growth_account (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE,
    total_growth_points BIGINT NOT NULL DEFAULT 0,
    current_level_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS biz_user_point_account (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE,
    total_earned_points BIGINT NOT NULL DEFAULT 0,
    total_spent_points BIGINT NOT NULL DEFAULT 0,
    balance_points BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(total_earned_points >= 0),
    CHECK(total_spent_points >= 0),
    CHECK(balance_points >= 0)
);

CREATE TABLE IF NOT EXISTS biz_growth_rule (
    id BIGINT PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    reward_points BIGINT NOT NULL,
    daily_limit BIGINT,
    weekly_limit BIGINT,
    monthly_limit BIGINT,
    cooldown_seconds INTEGER,
    requires_success BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    effective_from TIMESTAMPTZ,
    effective_to TIMESTAMPTZ,
    description VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS biz_point_rule (
    id BIGINT PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    reward_points BIGINT NOT NULL,
    daily_limit BIGINT,
    weekly_limit BIGINT,
    monthly_limit BIGINT,
    cooldown_seconds INTEGER,
    requires_success BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    effective_from TIMESTAMPTZ,
    effective_to TIMESTAMPTZ,
    description VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS biz_growth_event (
    id BIGINT PRIMARY KEY,
    event_id VARCHAR(128) NOT NULL UNIQUE,
    user_id BIGINT NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    source_id VARCHAR(128),
    event_type VARCHAR(128) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    event_data JSONB,
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS biz_user_growth_transaction (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    change_points BIGINT NOT NULL,
    balance_after BIGINT NOT NULL,
    rule_id BIGINT,
    source_type VARCHAR(64) NOT NULL,
    source_id VARCHAR(128),
    event_id VARCHAR(128),
    transaction_type VARCHAR(32) NOT NULL,
    description VARCHAR(500),
    operator_type VARCHAR(32) NOT NULL,
    operator_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS biz_user_point_transaction (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    change_points BIGINT NOT NULL,
    balance_after BIGINT NOT NULL,
    rule_id BIGINT,
    source_type VARCHAR(64) NOT NULL,
    source_id VARCHAR(128),
    event_id VARCHAR(128),
    transaction_type VARCHAR(32) NOT NULL,
    description VARCHAR(500),
    operator_type VARCHAR(32) NOT NULL,
    operator_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS biz_user_level_history (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    from_level_id BIGINT,
    to_level_id BIGINT NOT NULL,
    growth_points BIGINT NOT NULL,
    change_type VARCHAR(32) NOT NULL,
    reason VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS biz_user_level_benefit (
    id BIGINT PRIMARY KEY,
    level_id BIGINT NOT NULL,
    benefit_type VARCHAR(64) NOT NULL,
    benefit_code VARCHAR(128) NOT NULL,
    benefit_value JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS biz_cosmetic (
    id BIGINT PRIMARY KEY,
    code VARCHAR(128) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    cosmetic_type VARCHAR(32) NOT NULL,
    image_url VARCHAR(512),
    animation_url VARCHAR(512),
    rarity VARCHAR(32),
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    description VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS biz_user_cosmetic (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    cosmetic_id BIGINT NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    source_id VARCHAR(128),
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, cosmetic_id)
);

CREATE TABLE IF NOT EXISTS biz_user_equipment (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE,
    avatar_cosmetic_id BIGINT,
    avatar_frame_cosmetic_id BIGINT,
    crown_cosmetic_id BIGINT,
    badge_cosmetic_id BIGINT,
    title_cosmetic_id BIGINT,
    name_effect_cosmetic_id BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =========================
-- Tools
-- =========================

CREATE TABLE IF NOT EXISTS tool_category (
    id BIGINT PRIMARY KEY,
    parent_id BIGINT,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    icon_url VARCHAR(512),
    sort_order INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tool (
    id BIGINT PRIMARY KEY,
    category_id BIGINT NOT NULL,
    code VARCHAR(128) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    description VARCHAR(1000),
    component_key VARCHAR(128),
    execution_mode VARCHAR(32) NOT NULL,
    lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    visibility VARCHAR(32) NOT NULL DEFAULT 'PUBLIC',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_recommended BOOLEAN NOT NULL DEFAULT FALSE,
    tags JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tool_version (
    id BIGINT PRIMARY KEY,
    tool_id BIGINT NOT NULL,
    version VARCHAR(64) NOT NULL,
    config JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tool_id, version)
);

CREATE TABLE IF NOT EXISTS tool_component_registry (
    id BIGINT PRIMARY KEY,
    component_key VARCHAR(128) NOT NULL UNIQUE,
    component_type VARCHAR(32) NOT NULL,
    implementation_ref VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_access_policy (
    id BIGINT PRIMARY KEY,
    tool_id BIGINT NOT NULL,
    subject_type VARCHAR(32) NOT NULL,
    user_level_id BIGINT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    quota_config JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_usage_event (
    id BIGINT PRIMARY KEY,
    tool_id BIGINT NOT NULL,
    user_id BIGINT,
    anonymous_id_hash VARCHAR(128),
    result VARCHAR(32),
    duration_ms BIGINT,
    execution_mode VARCHAR(32),
    trace_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_usage_daily (
    id BIGINT PRIMARY KEY,
    tool_id BIGINT NOT NULL,
    stat_date DATE NOT NULL,
    total_count BIGINT NOT NULL DEFAULT 0,
    success_count BIGINT NOT NULL DEFAULT 0,
    failure_count BIGINT NOT NULL DEFAULT 0,
    guest_count BIGINT NOT NULL DEFAULT 0,
    user_count BIGINT NOT NULL DEFAULT 0,
    unique_user_count BIGINT NOT NULL DEFAULT 0,
    avg_duration_ms NUMERIC(18,2),
    UNIQUE(tool_id, stat_date)
);

CREATE TABLE IF NOT EXISTS tool_recent_usage (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    tool_id BIGINT NOT NULL,
    last_used_at TIMESTAMPTZ NOT NULL,
    use_count BIGINT NOT NULL DEFAULT 0,
    UNIQUE(user_id, tool_id)
);

CREATE TABLE IF NOT EXISTS tool_popularity_daily (
    id BIGINT PRIMARY KEY,
    tool_id BIGINT NOT NULL,
    stat_date DATE NOT NULL,
    score NUMERIC(20,6) NOT NULL DEFAULT 0,
    rank_no INTEGER,
    UNIQUE(tool_id, stat_date)
);

-- =========================
-- Blog
-- =========================

CREATE TABLE IF NOT EXISTS blog_author (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE,
    author_name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    approved_at TIMESTAMPTZ,
    approved_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blog_author_application (
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

CREATE TABLE IF NOT EXISTS blog_category (
    id BIGINT PRIMARY KEY,
    parent_id BIGINT,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blog_article (
    id BIGINT PRIMARY KEY,
    author_id BIGINT NOT NULL,
    category_id BIGINT,
    title VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    summary VARCHAR(1000),
    cover_url VARCHAR(512),
    content TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    published_at TIMESTAMPTZ,
    view_count BIGINT NOT NULL DEFAULT 0,
    like_count BIGINT NOT NULL DEFAULT 0,
    favorite_count BIGINT NOT NULL DEFAULT 0,
    comment_count BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS blog_article_version (
    id BIGINT PRIMARY KEY,
    article_id BIGINT NOT NULL,
    version_no INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    summary VARCHAR(1000),
    content TEXT NOT NULL,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(article_id, version_no)
);

CREATE TABLE IF NOT EXISTS blog_tag (
    id BIGINT PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blog_article_tag (
    article_id BIGINT NOT NULL,
    tag_id BIGINT NOT NULL,
    PRIMARY KEY(article_id, tag_id)
);

CREATE TABLE IF NOT EXISTS blog_comment (
    id BIGINT PRIMARY KEY,
    article_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    parent_id BIGINT,
    content TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PUBLISHED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS blog_like (
    user_id BIGINT NOT NULL,
    article_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, article_id)
);

CREATE TABLE IF NOT EXISTS blog_favorite (
    user_id BIGINT NOT NULL,
    article_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id, article_id)
);

CREATE TABLE IF NOT EXISTS blog_user_follow (
    follower_user_id BIGINT NOT NULL,
    followed_user_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(follower_user_id, followed_user_id),
    CHECK(follower_user_id <> followed_user_id)
);

-- =========================
-- Dictionary
-- =========================

CREATE TABLE IF NOT EXISTS sys_dict_type (
    id BIGINT PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    description VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sys_dict_item (
    id BIGINT PRIMARY KEY,
    dict_type_id BIGINT NOT NULL,
    value VARCHAR(128) NOT NULL,
    label VARCHAR(255) NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =========================
-- Suggested indexes
-- =========================

CREATE INDEX IF NOT EXISTS idx_biz_growth_tx_user_time
ON biz_user_growth_transaction(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_biz_point_tx_user_time
ON biz_user_point_transaction(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_biz_growth_event_user_time
ON biz_growth_event(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_tool_usage_tool_time
ON tool_usage_event(tool_id, created_at);

CREATE INDEX IF NOT EXISTS idx_blog_article_author_status
ON blog_article(author_id, status);

CREATE INDEX IF NOT EXISTS idx_blog_comment_article_time
ON blog_comment(article_id, created_at DESC);
