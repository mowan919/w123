# 14 AI Coding Agent 开发规范

## 1. AI 角色

AI 是实现者，不是需求制定者。

业务规则来自 Spec。

## 2. 必须读取

开始任何业务任务前：

1. AGENTS.md
2. SPEC_INDEX.md
3. 00-需求冻结确认表
4. 当前任务 Spec
5. 当前 Verification

## 3. 工作方式

```text
Read
→ Plan
→ Implement
→ Test
→ Verify
→ Fix
→ Verify
→ Report
```

## 4. 禁止

- 猜业务需求
- 大规模无关重构
- 修改冻结规则
- 删除测试绕过失败
- 只做前端权限
- 无 migration 改数据库模型
- 未验证就宣布完成

## 5. 未冻结事项

遇到未冻结事项：

- 明确标记
- 不把猜测当需求
- 可以提出技术候选
- 等人类确认

## 6. Commit

推荐小步提交：

```text
feat(auth): ...
feat(permission): ...
fix(session): ...
test(permission): ...
```

## 7. Completion

必须附：

- Changes
- DB
- API
- Tests
- Verification
- Risks
- Blocked
