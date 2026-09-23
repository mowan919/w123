# VCTN AI Coding Agent 工作协议

> 本文件是本项目所有 AI Coding Agent 的最高层开发工作协议。
> 业务需求以 `docs/spec/` 为准；验收标准以 `docs/verification/` 为准。

## 1. 项目目标

本项目为后台管理平台，后端技术栈：

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- Redis

核心能力包括：

- 组织与用户
- 多角色权限
- 角色继承
- Page / Menu / Button / API / Field / Data Scope 权限
- 登录、认证、Session
- MFA 扩展
- 审计、操作、安全、访问、应用日志
- Trace / Request ID
- 字典与系统参数
- 动态权限
- 安全控制

## 2. Spec 优先级

Agent 必须按以下优先级理解规则：

1. `docs/spec/00-需求冻结确认表.md`
2. 其他 `docs/spec/*.md`
3. `docs/agent/*.md`
4. 当前任务说明
5. 代码中的既有实现

如果代码与冻结 Spec 冲突，优先遵循 Spec，并在报告中指出需要修改的代码。

不得擅自修改已经冻结的业务规则。

## 3. 三阶段工作模型

所有任务必须遵循：

```text
SPEC
  ↓
PLAN
  ↓
IMPLEMENT
  ↓
VERIFY
  ↓
FIX
  ↓
VERIFY AGAIN
```

禁止直接从需求跳到“大规模编码”。

## 4. 单次任务边界

每次 Agent 任务必须明确：

- SPEC 编号
- 允许修改的模块
- 不允许修改的模块
- 数据库变更
- API 变更
- 测试范围
- Verification 文件

如果发现需要修改任务范围之外的模块：

1. 先停止扩展；
2. 记录问题；
3. 说明为什么需要扩展；
4. 除非任务明确授权，不得自行扩大范围。

## 5. 实现原则

### 5.1 后端权限必须由后端最终校验

前端隐藏菜单、页面、按钮不能作为安全边界。

必须：

```text
Frontend Permission
        +
Backend API Authorization
        +
Data Scope
```

### 5.2 SUPER_ADMIN

SUPER_ADMIN 是系统级角色。

- 可管理所有正常用户。
- 可将所有正常用户 Session 踢下线。
- 其他管理员不能踢 SUPER_ADMIN。
- SUPER_ADMIN 只能由本人退出登录。
- 相关规则必须集中实现，禁止散落在 Controller 中。

### 5.3 数据范围

部门管理员默认：

```text
当前部门 + 所有子部门
```

角色支持：

```text
ALL
DEPARTMENT
DEPARTMENT_CHILDREN
SELF
CUSTOM
```

### 5.4 多角色

用户可以拥有多个角色。

有效权限：

```text
Effective Permission = Union(User Roles)
```

角色继承产生的权限必须计入最终权限计算。

### 5.5 权限即时生效

权限修改默认立即生效。

如果使用 Redis 缓存，必须设计：

- permission version
- cache invalidation
- stale cache protection

禁止出现“修改权限后必须重新登录才能生效”的隐藏行为。

## 6. ID 与时间

业务 ID：

- BIGINT
- Snowflake
- API JSON 中统一序列化为字符串
- 不使用自增业务 ID
- 不使用 UUID 作为业务主键

时间：

- 数据库存 UTC
- API 按项目统一规范转换
- 字段命名 snake_case

## 7. 删除

业务数据默认逻辑删除：

```text
deleted_at
```

查询必须考虑 soft delete。

唯一约束必须考虑逻辑删除后的重建问题。

## 8. 安全要求

不得：

- 记录明文密码
- 记录密码 hash 到普通日志
- 记录 MFA Secret
- 记录完整 Refresh Token
- 在异常信息中泄漏 Secret
- 将权限校验只放在前端

日志敏感信息：

- 手机：`138****1234`
- 邮箱：`abc***@example.com`
- Token：仅保留前 6 个字符
- Password：绝不记录
- MFA Secret：绝不记录

## 9. 修改数据库

任何数据库结构修改必须：

1. 修改 SQLAlchemy Model；
2. 生成 Alembic migration；
3. 检查升级；
4. 检查必要的索引、唯一约束、FK；
5. 检查 soft delete；
6. 运行相关测试。

禁止只修改 Model 而不生成 migration。

## 10. API

Base：

```text
/api/v1/admin
```

成功：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

失败：

```json
{
  "code": 403001,
  "message": "permission denied",
  "data": null
}
```

业务 ID JSON 返回字符串。

## 11. Trace

请求必须支持：

- X-Trace-ID
- X-Request-ID

如果请求没有传入，则自动生成。

Trace 必须能够贯穿：

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

## 12. 完成定义

Agent 只有同时满足以下条件才可以声明完成：

- Spec 对照完成
- 单元测试通过
- 集成测试通过（任务涉及则必须）
- 安全测试通过（任务涉及则必须）
- Alembic migration 正常
- lint / type check 按项目现状执行
- 无明显 TODO 遗留
- 无未解释的测试失败
- Verification 清单全部通过或明确记录 Blocked 项

## 13. 输出格式

每次任务完成后必须输出：

```text
# Implementation Report

## 1. Spec
- SPEC-xxx

## 2. Changes
- 文件：
- 模块：
- 数据库：

## 3. API
- 新增：
- 修改：

## 4. Tests
- Unit:
- Integration:
- Security:

## 5. Verification
- Passed:
- Failed:
- Blocked:

## 6. Risks
- ...

## 7. Follow-up
- ...
```

## 14. 禁止事项

禁止：

- 为了通过测试修改测试来掩盖实现问题；
- 未经确认修改冻结业务规则；
- 一次性重构无关模块；
- 删除现有功能来绕过冲突；
- 将安全校验放到前端代替后端；
- 以“未来再做”为由跳过当前 Spec 必须项。
