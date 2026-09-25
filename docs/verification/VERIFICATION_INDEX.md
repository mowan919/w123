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
| 007 | Dictionary | **PASS**（18/18，0 BLOCKED） | `007-dictionary-result.md`（2026-09-25） |
| 008 | Dynamic Permission | **PASS**（11/11，0 BLOCKED） | `008-dynamic-permission-result.md`（2026-09-25） |
| 009 | Hardening | **PASS**（12/12，0 BLOCKED） | `009-hardening-result.md`（2026-09-25） |
| 010 | Final Acceptance | **PASS**（29/29，0 BLOCKED） | `010-final-acceptance-result.md`（2026-09-25） |

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

> ✅ **007 已判定 PASS（18/18，0 BLOCKED）**：`05 §2` / `05 §3` 的字段逐项落地，
> `05 §3` 的"同字典 `item_value` 软删除感知唯一"由 **partial unique index**
> 在数据库层保证（服务层预校验只负责给出友好的 409），删除一律逻辑删除，
> `05 §4` 的 9 条管理端点 + 1 条公开查询端点以 `openapi()` **正向钉住**，
> `05 §5` 的 System Parameter 以"分表 / 分服务 / 分端点 / 分权限位"落地并与
> Dictionary 分离（含 AST 级"禁止互相导入"护栏）。
>
> ⚠️ Spec 缺了两项：系统参数**表名**与**端点路径**（`05 §5` 只有一句"必须有
> 类型/默认值/状态/描述和审计"，`08 §9` 的 Endpoint 清单里也只有 Dictionary）。
> 本 Phase 按最小推导补齐并逐条登记为 `INTERIM-7-01` / `INTERIM-7-04`
> （`docs/DESIGN-DECISIONS.md §14.1`），**不构成阻塞** ——
> 改动面分别是"一次 migration + 一处 `__tablename__`"与"一处 `include_router` 前缀"。
>
> ⚠️ 本 Phase 发现并修复三处缺陷（`§14.2` / `§14.3`）：其中
> **FINDING-7-01** 是**安全分支失效** —— `get_auth_service` 构造的 `MfaService`
> 一直使用默认（空）策略解析器，导致角色级 MFA 策略在登录路径上完全不生效，
> Phase 5 的"策略要求但无 Provider 即 fail-closed"分支**永远不会触发**。
> Phase 5 的测试全部直接构造服务并注入 resolver，因此没有一条用例覆盖
> 依赖装配路径 —— 这也说明"工厂函数返回什么"必须有测试。
> 修复后该分支已恢复（方向：收紧）。

> ✅ **008 已判定 PASS（11/11，0 BLOCKED）**：`09 §2` 的七段契约
> （pages / menus / buttons / apis / fields / data_scope / permission_version）
> 全部落地于 `GET /auth/permissions`；DD-20 遗留的"资源 CRUD HTTP 暴露"
> 以 8 条 `/admin/permission-resources*` 端点交付；`08 §7` 的角色授权与
> 数据范围端点逐条显式声明（不合并为 `/permissions/{kind}`，否则 Phase 10
> 的路径比对会判缺失）。第 9 项"前端可动态生成 route/menu"以**测试内独立消费者**
> 证明契约充分性 —— 它只读响应、不读库、不引用任何 Python 权限常量。
>
> ⚠️ 三项需要留意：
> 1. ~~**FINDING-8-01（未关闭）**~~ → ✅ **已于 Phase 9 关闭**：
>    `08 §4/§6/§7` 冻结的 Users / Departments / Roles **实体 CRUD 的 HTTP 面**
>    此前只有服务层（根因：`001` / `002` 裁判项全是服务层判定、不含端点存在性，
>    所以 Phase 1 / 2 PASS 时不会暴露）。Phase 9 补交付 14 条端点。
> 2. **DD-21 仍未冻结**，但本 Phase **未做需要裁定的行为变更**：
>    `build()` 默认行为完全不变，只对新增读路径启用拒绝型上下文
>    （`docs/DESIGN-DECISIONS.md §15.5`），**待人类追认**。
> 3. `08 §3–§9` **未列出**资源 CRUD 端点路径，本 Phase 按既有复数资源命名
>    取 `/admin/permission-resources*` 并登记为 `INTERIM-8-01`。
>
> ⚠️ `docs/DESIGN-DECISIONS.md §12.1` 的既定安排已兑现：
> MFA 的 system 级默认值由**系统参数表**提供（Seed 行 `700001`），
> 行缺失时回退环境变量（= 迁移前口径，不制造可用性事故），
> 行停用或类型不符则 fail-closed。端到端用例覆盖三种取值下的登录行为。

> ✅ **009 已判定 PASS（12/12，0 BLOCKED）**：限流（登录双维 + MFA IP 维）、
> 安全响应头、错误遮蔽、并发保护、幂等、无缓存/stale、迁移安全检查、
> 索引与外键实查全部成立。修复 2 个真实缺陷（FINDING-9-01 密钥脱敏漏掉
> JSON 形状、FINDING-9-02 PUT 部分更新被当成清空），关闭 1 个交付缺口
> （FINDING-8-01 组织实体 CRUD 的 HTTP 面）。
>
> ⚠️ 该结果文件的门禁数字**已于 Phase 10 复核时更正**：原写 `1208 passed`
> 是中间状态，Phase 9 提交（`623b08b`）的真实收集数是 **1213**（已用临时
> worktree 复核）。结论不变，只有数字更正。

> ✅ **010 已判定 PASS（29/29，0 BLOCKED）**：Build 4/4、Functional 12/12、
> Security 8/8、Permission Matrix 5/5。Build 四项为**实跑**（uvicorn 启动、
> `alembic upgrade head`、Redis 探针、四个健康检查端点），非推断。
>
> ⚠️ 本次验收抓到 **FINDING-10-01**：`08 §8` 冻结的审计 / 链路读端点
> （`GET /audit/logs*`、`GET /traces*`）**一条都不存在** ——
> 根因是 Phase 6 的 35 项裁判**全是落库判定**，没有一项问"能不能读出来"。
> 这是与 FINDING-8-01 同类的第二次发生：**裁判项只判服务层，
> 于是"HTTP 面不存在"永远判不出来**。已补交付 4 条端点 + 13 例测试，
> 并以"路由面逐条钉住"作为防再犯网。
>
> ⚠️ 另修正 **FINDING-10-02**（docstring 与实现不符）：改的是文档不是实现 ——
> 范围外单读返回 403 是**正确**的，它附带 FAILURE 审计，
> 改成 404 会让"谁试图访问谁"的取证记录消失。
>
> **PROJECT FINAL ACCEPTANCE: PASS**
