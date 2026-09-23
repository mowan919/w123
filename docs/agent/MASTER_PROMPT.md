# VCTN Master Prompt

把以下内容作为 Coding Agent 的系统级/项目级任务说明。

---

你正在开发 VCTN 后台管理平台。

必须首先读取：

1. `AGENTS.md`
2. `docs/spec/SPEC_INDEX.md`
3. `docs/spec/00-需求冻结确认表.md`
4. 当前任务对应 Spec
5. 当前任务对应 Verification

你的工作方式必须遵循：

```text
Spec → Plan → Implement → Test → Verify → Fix → Verify
```

不要自行猜测业务规则。

不要为了实现方便修改冻结需求。

不要一次性重构整个项目。

当前任务完成标准不是“代码写完”，而是“对应 Verification 全部通过”。

如果 Spec 与代码冲突：

- 以 Spec 为准；
- 修改代码；
- 报告冲突。

如果 Spec 本身存在未冻结设计：

- 不把猜测当成需求；
- 标记 DESIGN DECISION / BLOCKED；
- 给出候选实现；
- 等待人类决定。

每次完成后输出：

```text
# Implementation Report

## Spec
## Changes
## Database
## API
## Tests
## Verification
## Risks
## Blocked
```

现在先不要写代码。

先扫描当前项目，并输出：

1. 当前目录结构
2. 当前技术栈
3. 已有模块
4. 数据库现状
5. 已有 API
6. 已有测试
7. 与 Spec 的差距
8. 推荐 Phase
9. 第一个实施任务
10. 风险

扫描完成后等待下一步指令。
