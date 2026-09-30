# 04 Tools 工具域

## 1. tool_category

```sql
CREATE TABLE tool_category (
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
```

## 2. tool

```sql
CREATE TABLE tool (
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
```

execution_mode：

```text
FRONTEND
BACKEND
ASYNC
```

lifecycle：

```text
DRAFT
TESTING
ACTIVE
DISABLED
```

## 3. tool_version

记录工具版本、配置版本和发布版本。

## 4. tool_component_registry

`component_key` 映射到受控实现。

管理员不得填写任意 Vue import path。

## 5. tool_access_policy

访问主体：

```text
GUEST
USER_LEVEL
```

USER_LEVEL 必须有 `user_level_id`。

不设置 ADMIN 工具用户身份。

## 6. tool_usage_event

记录：

- tool_id
- user_id nullable
- anonymous_id_hash nullable
- result
- duration
- execution_mode
- trace_id
- created_at

禁止：

- password
- token
- secret
- 完整代码
- SQL
- 工具输入内容
- 文件内容

## 7. tool_usage_daily

按工具/日期聚合：

- total_count
- success_count
- failure_count
- guest_count
- user_count
- unique_user_count
- avg_duration_ms

## 8. tool_recent_usage

用于用户最近使用工具。

## 9. tool_popularity_daily

用于热门排序计算。

## 10. Redis

游客额度：

```text
tool:quota:guest:{anonymous_id_hash}:{tool_id}:{yyyyMMdd}
```

用户额度：

```text
tool:quota:user:{user_id}:{tool_id}:{yyyyMMdd}
```

限流：

```text
tool:rate:guest:{anonymous_id_hash}:{tool_id}:{window}
tool:rate:user:{user_id}:{tool_id}:{window}
tool:rate:ip:{ip_hash}:{tool_id}:{window}
```

使用 INCR/Lua，禁止 GET + SET 竞态实现。

## 11. Tools 与成长中心

工具成功执行后发布：

```text
TOOL_EXECUTION_SUCCESS
```

成长中心决定是否奖励。
