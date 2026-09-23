# VCTN Implementation Phases

## Phase 0 — 项目基线

目标：

- 建立 FastAPI 项目结构
- PostgreSQL
- SQLAlchemy
- Alembic
- Redis
- 配置管理
- 基础异常
- Response Envelope
- Trace / Request ID
- 日志基础设施
- 测试基础设施

禁止实现业务权限。

---

## Phase 1 — Organization / User

实现：

- Department
- User
- User status
- Department tree
- User CRUD
- Disable / Enable
- Logical delete
- Department Admin scope

验收：

`docs/verification/001-organization-user.md`

---

## Phase 2 — Role / Permission

实现：

- Role
- User multi-role
- Role inheritance
- Page
- Menu
- Button
- API
- Field
- Data Scope
- Effective permission calculation

验收：

`docs/verification/002-permission.md`

---

## Phase 3 — Authentication

实现：

- Login
- Password policy
- Failed attempts
- Lockout
- Password reset
- Forced password change
- Logout
- Refresh
- Current user

验收：

`docs/verification/003-authentication.md`

---

## Phase 4 — Session

实现：

- Online status
- Session list
- Revoke one
- Revoke all
- Super Admin protection
- Department Admin scope

验收：

`docs/verification/004-session.md`

---

## Phase 5 — MFA

实现可扩展 MFA Provider 架构。

注意：

V1 Provider 未冻结时，不得自行宣布具体 Provider 为需求事实。

验收：

`docs/verification/005-mfa.md`

---

## Phase 6 — Audit / Security / Access / Operation / Trace

实现：

- Access Log
- Security Log
- Operation Log
- Audit Log
- Application Log
- Trace ID
- Request ID
- Sensitive masking
- Retention foundation

验收：

`docs/verification/006-logging-audit.md`

---

## Phase 7 — Dictionary / System Parameter

实现：

- Dictionary Type
- Dictionary Item
- System Parameter
- Admin APIs
- Public dictionary query

验收：

`docs/verification/007-dictionary.md`

---

## Phase 8 — Dynamic Frontend Permission Contract

实现后端权限输出：

- page
- menu
- button
- api
- field
- data scope

前端动态生成页面/菜单/按钮。

验收：

`docs/verification/008-dynamic-permission.md`

---

## Phase 9 — Hardening

实现/检查：

- Cache invalidation
- Idempotency
- Rate limit
- Concurrency
- Security headers
- Error masking
- Audit integrity
- Migration safety
- Performance baseline

验收：

`docs/verification/009-hardening.md`

---

## Phase 10 — Final Acceptance

执行：

- Full test
- Permission matrix
- Security review
- Migration test
- API contract test
- Trace verification
- Log masking verification

验收：

`docs/verification/010-final-acceptance.md`
