# PHASE-001 Project Baseline

## Spec

- 总体需求
- 数据库设计
- API 规范
- AI Coding Agent 开发规范

## Scope

实现项目基础设施：

- FastAPI application
- settings/config
- PostgreSQL connection
- SQLAlchemy
- Alembic
- Redis
- health check
- API response envelope
- exception handling
- Trace ID
- Request ID
- test foundation
- logging foundation

## 禁止

本阶段不要实现：

- User CRUD
- Role
- Permission
- MFA
- Session business logic
- Dictionary business logic

## Verification

必须完成：

- application start
- health endpoint
- database migration
- Redis connection
- test runner
- trace propagation
- response envelope
