# Spec → Agent → Verification Coding Protocol

## 1. 核心思想

AI 不负责“猜需求”。

AI 的职责：

```text
读取 Spec
→ 分解任务
→ 实现
→ 测试
→ 根据 Verification 自检
→ 修复
```

## 2. 标准任务生命周期

### Step 1：Spec

确定：

- SPEC 编号
- 目标
- 范围
- 约束
- 输入输出
- 验收条件

### Step 2：Plan

Agent 必须先输出：

- 影响模块
- 数据库变化
- API变化
- 类/函数设计
- 测试计划
- 风险

除非任务明确要求直接实施，否则 Plan 阶段不修改代码。

### Step 3：Implement

只实现当前 Spec。

### Step 4：Verify

至少执行：

- 编译/启动检查
- 单元测试
- 与任务相关的集成测试
- Verification checklist

### Step 5：Fix

失败项必须修复。

修复后重新运行受影响测试。

### Step 6：Report

输出最终 Implementation Report。

## 3. 不确定事项

遇到以下情况不要猜：

- MFA V1 Provider 未冻结
- Token 生命周期未冻结
- Redis Key 未冻结
- 自定义 Data Scope 存储方式未冻结
- Secret Manager 未冻结

处理方式：

```text
发现未冻结项
→ 标记 BLOCKED / DESIGN DECISION
→ 不擅自改变业务需求
→ 如果存在安全默认值，可在技术层采用保守实现，但必须报告
```

## 4. 小步提交

推荐每个 Phase 对应一个或多个小提交：

```text
feat(auth): implement login
feat(session): implement session management
feat(permission): implement permission engine
test(permission): add permission matrix tests
```

## 5. AI 自检问题

完成后必须回答：

1. 我实现了哪个 Spec？
2. 有没有实现 Spec 之外的东西？
3. 哪些数据库发生变化？
4. 哪些 API 发生变化？
5. 哪些权限边界发生变化？
6. 有没有越权风险？
7. 有没有遗漏测试？
8. 有没有冻结决策仍未实现？
