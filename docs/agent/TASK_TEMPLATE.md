# AI Coding Task Template

复制本模板给 Coding Agent。

---

执行任务：`SPEC-XXX`

## 1. 阅读

先阅读：

- `AGENTS.md`
- `docs/spec/00-需求冻结确认表.md`
- `docs/spec/SPEC_INDEX.md`
- `docs/spec/XXX-xxxx.md`
- 对应 `docs/verification/XXX-xxxx.md`

如任务涉及数据库，再阅读：

- `docs/spec/07-数据库设计.md`

如任务涉及 API，再阅读：

- `docs/spec/08-API规范.md`

如任务涉及安全，再阅读：

- `docs/spec/10-安全设计.md`

## 2. 第一阶段：Plan

先不要大规模修改代码。

输出：

- 当前代码结构理解
- Spec 要求
- 影响文件
- DB 变化
- API 变化
- 实现步骤
- 测试方案
- 风险

## 3. 第二阶段：Implement

按照 Plan 实现。

要求：

- 只修改任务范围
- 不改变冻结业务规则
- 不删除无关功能
- 数据库变化必须有 Alembic migration
- 安全校验必须在后端

## 4. 第三阶段：Verify

执行：

- unit tests
- integration tests（如适用）
- security tests（如适用）
- lint/type check（如项目已配置）
- 对应 Verification checklist

## 5. 第四阶段：Fix

所有失败项：

- 定位原因
- 修改实现
- 重新测试

## 6. 最终输出

```text
# Implementation Report

Spec:
Changes:
Database:
API:
Tests:
Verification:
Risks:
Blocked:
```

不要只说“完成”。
