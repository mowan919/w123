# 06 日志、审计与 Trace

## 1. Log Categories

### Access Log
请求访问信息。

Retention: 30 days.

### Security Log
登录、锁定、MFA、密码、Session、安全事件。

Retention: 180 days.

### Operation Log
普通业务操作。

Retention: 180 days.

### Audit Log
高价值业务变更与管理员行为。

Retention: 2 years.

### Application Log
应用运行日志。

Retention: 30 days.

## 2. Audit

必须包含：

- audit_log_id
- trace_id
- request_id
- operator_id
- operator_username
- action
- resource_type
- resource_id
- before_data
- after_data
- result
- error_code
- ip
- user_agent
- created_at

Audit append-only。

## 3. Trace

支持：

- X-Trace-ID
- X-Request-ID

缺失时自动生成。

传播：

```text
HTTP
 ↓
Controller
 ↓
Service
 ↓
Repository
 ↓
Audit/Security Log
```

## 4. Masking

- phone → `138****1234`
- email → `abc***@example.com`
- token → first 6 chars
- password → never log
- MFA Secret → never log

## 5. Retention

必须提供后续归档/清理能力。

生产环境建议按日志量采用分区、归档或批量清理。
