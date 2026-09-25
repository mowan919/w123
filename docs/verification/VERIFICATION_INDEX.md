# Verification Index

| 编号 | 验收 |
|---|---|
| 001 | Organization / User |
| 002 | Permission |
| 003 | Authentication |
| 004 | Session |
| 005 | MFA |
| 006 | Logging / Audit / Trace |
| 007 | Dictionary |
| 008 | Dynamic Permission |
| 009 | Hardening |
| 010 | Final Acceptance |

## 状态

每项使用：

- PASS
- FAIL
- BLOCKED
- NOT RUN

禁止用“基本完成”作为最终状态。

### 执行现状

| 编号 | 验收 | 状态 | 结果文件 |
|---|---|---|---|
| 001 | Organization / User | **PASS**（13/13，0 BLOCKED） | `001-organization-user-result.md`（2026-09-24 **补做**） |
| 002 | Permission | **PASS** | `002-permission-result.md` |
| 003 | Authentication | **PASS** | `003-authentication-result.md` |
| 004 | Session | **PASS** | `004-session-result.md`（2026-09-24，15/15，0 BLOCKED） |
| 005 | MFA | **PASS**（13/13，0 BLOCKED） | `005-mfa-result.md`（2026-09-25） |
| 006 | Logging / Audit / Trace | **PASS**（35/35，0 BLOCKED） | `006-logging-audit-result.md`（2026-09-25） |
| 007 | Dictionary | NOT RUN | — |
| 008 | Dynamic Permission | NOT RUN | — |
| 009 | Hardening | NOT RUN | — |
| 010 | Final Acceptance | NOT RUN | — |

> ✅ **001 的缺口已于 2026-09-24 关闭**：该项曾长期停在 `NOT RUN ——
> 实现早已提交（`ec66678`），但从未产出过结果文件，不能因为"代码已经写了"就记成 PASS。
> 本次按裁判书**逐项重新判定**（13/13 PASS，0 BLOCKED），
> 结果见 `001-organization-user-result.md`。
> 判定对象是当前代码（`e0665fe`）而非历史快照 ——
> 若 Phase 2~4 的演进曾**退化**过 Phase 1 的能力，本次判定有责任把它暴露为 FAIL。
> 顺带发现并修复了一处依赖缺陷（见结果文件 FINDING-1-01）。

> ✅ **005 的 BLOCKED 已解除**：该项起初在**编码前**即被四个未冻结的技术设计决策阻塞
> （`DD-01` 具体 Provider / `DD-22` Secret 加密方案 / `DD-23` 挑战与续接机制 /
> `DD-24` 策略与凭据存储模型），外加裁判第 12 项"恢复流程不会泄漏 Secret"
> **在 `docs/spec/` 中没有任何依据**。正式决策请求见 `docs/DECISION-REQUEST-PHASE-5.md`。
>
> 人类随后下达"不要询问我，完成所有任务"，Agent 依据该请求中已写明的**草案 A** 继续执行，
> **只采用不与 Frozen Spec 冲突的选项**：不选定产品级 Provider（`00 §4` 明令禁止）、
> 不新增恢复流程（属新增业务能力）、不把系统参数提前建表（属 Phase 7）。
> 逐条取舍登记在 `docs/DESIGN-DECISIONS.md §12`，结果见 `005-mfa-result.md`（13/13 PASS）。
>
> ⚠️ 裁判第 12 项的读法**仍待人类澄清**：本次取 (c)"不新增恢复流程"，
> 并以自动化护栏钉住"Secret 只在 setup 流出一次"。若裁定为 (a) 恢复码 /
> (b) 管理员重置 MFA，则需**新增**表与端点，届时应重跑本验收。

> ✅ **006 已判定 PASS（35/35，0 BLOCKED）**：`06 §1` 的五类日志全部落库，
> `06 §3` 的 Trace 四项全部成立，`06 §2` 的 15 个 Audit 字段一字不缺且
> **append-only 由数据库触发器强制**（非"ORM 里没写 update 方法"的约定），
> `06 §4` 的五条脱敏规则首次覆盖**消息正文**与异常堆栈，
> `06 §5` 的保留期清理能力以 `LogRetentionService` + `scripts/purge_logs.py` 交付。
> DD-08（日志分区）仍未冻结 → 按 `06 §5` 的"**后续**归档/清理能力"口径
> 不分区、纯增量延后（`JUDGMENT-6-01`），**不构成阻塞**。
>
> ⚠️ 本 Phase 顺带关闭了一个此前**无裁判项命中**的真实缺口：Phase 2~5 的
> `app/api/deps.py` 用 `NullAuditRecorder` 构造全部服务，**所有审计事件
> 止步于内存**，从未落库（详见 `docs/DESIGN-DECISIONS.md §13.5`）。
