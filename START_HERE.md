# VCTN AI Coding — Start Here

## 已修复

本版本已经包含完整的 `docs/spec/`：

- `SPEC_INDEX.md`
- `00-需求冻结确认表.md`
- `01-总体需求.md`
- ...
- `16-完整性检查.md`

共 **17 个 Spec 文档**，不再只有索引。

## 安装

将本包解压/合并到：

```text
D:\lemon\vctn
```

最终结构：

```text
vctn/
├── AGENTS.md
├── START_HERE.md
├── docs/
│   ├── spec/            # 17 个完整 Spec
│   ├── agent/           # Agent 协议与 Phase
│   └── verification/   # Verification 验收
└── scripts/
```

## 第一次让 AI 做什么

不要直接写代码。

发送：

> 阅读 AGENTS.md、START_HERE.md、docs/spec/SPEC_INDEX.md、docs/spec/00-需求冻结确认表.md 和 docs/agent/MASTER_PROMPT.md。
>
> 不要修改代码。
>
> 扫描当前项目，输出：
> 1. 当前目录结构
> 2. 技术栈
> 3. 已有模块
> 4. 数据库现状
> 5. API 现状
> 6. 测试现状
> 7. 当前代码与 Spec 的差距
> 8. 风险
> 9. 推荐 Phase
>
> 扫描完成后停止，等待确认。

## 然后

从：

```text
docs/agent/PHASE-001-PROJECT-BASELINE.md
```

开始。

每一个 Phase：

```text
Spec
→ Agent Plan
→ Implement
→ Verification
→ Fix
→ Verification
→ PASS
```

再进入下一 Phase。
