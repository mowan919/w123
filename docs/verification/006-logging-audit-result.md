# Verification 006 —— Logging / Audit / Trace（结果）

- 裁判书：`docs/verification/006-logging-audit.md`（35 项）
- 判定日期：2026-09-25
- 判定对象：当前工作区代码（Phase 6 全量改动）
- 实现依据：`docs/spec/06-日志审计与Trace.md`、`10-安全设计.md` §4/§8、
  `07-数据库设计.md` §8/§9、`13-运维部署.md` §5

## 1. 逐项判定（35/35）

### 1.1 日志类型（5 项，Spec `06 §1`）

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 1 | Access Log | 请求访问信息落库，保留 30 天 | `access_logs` 表；中间件在响应末分片前写入 method/path/status/duration/ip/ua/trace/request/operator | **PASS** | `app/models/logs.py::AccessLog`、`app/middleware/trace.py::finish`、迁移 `phase6_dd08`；`tests/test_trace_access_log.py`（13） |
| 2 | Security Log | 登录/锁定/MFA/密码/Session/安全事件，保留 180 天 | `security_logs` 表；`SECURITY_ACTIONS`（13 个动作）切片的独立落点；`reason` 列可检索 | **PASS** | `app/models/logs.py::SecurityLog`、`app/audit/classify.py`；`tests/test_log_repository.py::TestDispatch`/`TestFailureForensics` |
| 3 | Operation Log | 普通业务操作，保留 180 天 | `operation_logs` 表；`OPERATION_ACTIONS`（20 个动作）切片；只读动作**不**进入 | **PASS** | `app/audit/classify.py`、`tests/test_log_repository.py::test_read_only_actions_stay_out_of_operation_log` |
| 4 | Audit Log | 高价值变更与管理员行为，保留 2 年 | `audit_logs` 表；**全部**审计动作无条件先写；append-only | **PASS** | `app/repositories/logs.py::LogRepository._append`、迁移 `phase6_dd08`；`tests/test_log_repository.py`（33） |
| 5 | Application Log | 应用运行日志，保留 30 天 | `application_logs` 表；经 `DbLogHandler` 投递（INFO 及以上） | **PASS** | `app/core/logging.py::DbLogHandler`、`tests/test_log_pipeline.py::TestDbLogHandler` |

> 五类切片的完整性由**可执行断言**保证：
> `SECURITY ∪ OPERATION ∪ READ_ONLY == set(AuditAction)` 且两两不相交
> （`tests/test_log_classification.py`）。新增动作忘分类 → CI 立刻失败，
> 而不是静默地只进审计表。

### 1.2 Trace（4 项，Spec `06 §3`）

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 6 | `X-Trace-ID` | 支持传入并使用调用方值 | 传入即采用（去空白、限长 ≤128），并回写响应头 | **PASS** | `app/middleware/trace.py::_resolve_id`；`tests/test_trace_access_log.py::test_provided_ids_are_echoed_back` |
| 7 | `X-Request-ID` | 同上 | 同上，且与 trace 独立生成/回写 | **PASS** | 同上；`test_request_id_is_recorded` |
| 8 | 无 Header 时自动生成 | 缺失即生成 | 生成 32 位十六进制（`uuid4().hex`）；超长传入值被替换并记 WARNING | **PASS** | `app/core/context.py::new_trace_id`；`test_missing_ids_are_generated`、`test_overlong_id_is_replaced` |
| 9 | HTTP → Controller → Service → Repository → Log 链路一致 | 同一次请求的 trace 在日志中可检索 | ContextVar 绑定（纯 ASGI 中间件），`AuditEvent.build` / `AccessRecord.build` / `ApplicationRecord.build` 自动取上下文；落库后可按 `trace_id` 查到该请求的全部日志 | **PASS** | `app/core/context.py`、`app/audit/events.py`、`app/audit/records.py`；`tests/test_trace_access_log.py::test_not_found_request_is_logged`（按响应头里的 trace 反查数据库行） |

### 1.3 Audit（16 项，Spec `06 §2`）

`tests/test_log_repository.py::TestAuditFieldContract::test_audit_table_has_exactly_the_spec_fields`
断言 `set(audit_logs.columns) == {15 个 Spec 字段}`（含 `id` 即 `audit_log_id`），
因此下面 15 行的 EVIDENCE 共用同一处断言 + 各字段的落库用例。

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 10 | `audit_log_id` | BIGINT + Snowflake 主键 | `BigInteger, primary_key=True, autoincrement=False`，Python 侧 `next_id()`；API/JSON 无关（日志不对外暴露） | **PASS** | `app/db/base.py::PrimaryKeyMixin`；`test_audit_log_id_uses_snowflake_bigint`、`test_rows_added_later_have_larger_ids` |
| 11 | `trace_id` | 存在且为链路值 | `String(128)` 可空；写入由上下文自动填充 | **PASS** | 模型列断言 + `test_provided_ids_are_echoed_back` |
| 12 | `request_id` | 同上 | `String(128)` 可空 | **PASS** | `test_request_id_is_recorded` |
| 13 | `operator_id` | 操作者 ID，未知时为 NULL | `BigInteger` 可空；不编造身份 | **PASS** | `test_unknown_operator_is_preserved_as_null` |
| 14 | `operator_username` | 审计用登录名 | `String(64)`（= 用户名上界），可空 | **PASS** | 列宽断言 + 同上用例 |
| 15 | `action` | 动作名 | `String(64)`，取自 `AuditAction` | **PASS** | `TestDispatch` 各用例 |
| 16 | `resource_type` | 资源类型 | `String(64)` 必填 | **PASS** | 同上 |
| 17 | `resource_id` | 资源 ID；非单一资源为 NULL | `BigInteger` 可空 | **PASS** | `test_reason_is_promoted_to_security_log`（`resource_id=None`） |
| 18 | `before_data` | 变更前数据，**已脱敏** | `JSONB`；`LogBuffer.add_audit` 在**入缓冲时**递归脱敏 | **PASS** | `app/audit/buffer.py::_scrub_event`；`tests/test_log_pipeline.py::TestAuditPayloadsAreScrubbedBeforeBuffering` |
| 19 | `after_data` | 变更后数据，**已脱敏** | 同上；同时承载失败原因 `reason` | **PASS** | 同上 + `test_reason_is_promoted_to_security_log` |
| 20 | `result` | `SUCCESS` / `FAILURE` | `String(16)` 必填 | **PASS** | `TestFailureForensics` |
| 21 | `error_code` | 失败时的业务错误码 | `Integer` 可空 | **PASS** | `test_reason_is_promoted_to_security_log`（`error_code=429001`） |
| 22 | `ip` | 来源 IP | `String(64)` 可空；只取 socket 对端，**不读 XFF** | **PASS** | `app/api/deps.py::client_ip` 同口径（`app/middleware/trace.py::_client_ip`） |
| 23 | `user_agent` | UA | `String(512)` 可空；超长在写入前截断（**INTERIM-6-03**，防整批日志丢失） | **PASS** | `test_long_user_agent_is_truncated_not_rejected`、`test_naive_overlong_write_would_have_failed`（反证） |
| 24 | `created_at` | 发生时间 (UTC) | `DateTime(timezone=True)` 必填 | **PASS** | `test_created_at_round_trips_as_utc` |
| 25 | Audit append-only | 记录不可篡改 | 两道防线：① 模型无 `updated_at`（结构上没有可更新列）；② 数据库触发器拒绝 UPDATE / 未声明意图的 DELETE / TRUNCATE | **PASS** | 迁移 `phase6_dd08::_install_append_only_guards`；`tests/test_log_repository.py::TestAppendOnlyTriggers`（含 `pg_trigger` 反查） |

### 1.4 Masking（5 项，Spec `06 §4` / `10 §4`）

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 26 | `phone` → `138****1234` | 结构化字段与**自由文本**均脱敏 | 键名规则（`mask_phone`）+ 文本规则（`_PHONE_RE`，仅匹配 `1[3-9]` 11 位，`(?!\d)` 保护 Snowflake ID） | **PASS** | `app/core/masking.py`；`tests/test_masking_text.py`（29） |
| 27 | `email` → `abc***@example.com` | 同上 | `mask_email` + `_EMAIL_RE` | **PASS** | 同上 |
| 28 | `token` → 只保留前 6 字符 | 具名 token 字段保留前 6；自由文本整体 `<redacted>`（**INTERIM-6-09**，取 `10 §4` 更严措辞） | `mask_token` / `_SECRET_PAIR_RE` / `_JWT_RE` | **PASS** | `test_token_only_first_six_chars_is_not_enough_for_free_text` |
| 29 | `password` → never log | 任何路径都不出现明文 | `NEVER_LOG_KEYS` 键名规则 + 自由文本 `_SECRET_PAIR_RE`；`scrub_text` 作用于 `record.msg`、exceptions、extras | **PASS** | `tests/test_masking_text.py::TestMaskingFilterRewritesMessage` / `TestFormattersMaskSensitiveText` |
| 30 | MFA Secret → never log | 同上 | `mfa_secret` / `totp_secret` / `otp_secret` / `secret` 均在 `NEVER_LOG_KEYS` 与文本规则中 | **PASS** | 同上；另见 `test_mfa_management.py::TestSecretNeverLeavesAudit` |

> **Phase 6 之前这条路径是断的**：`scrub()` 只认键名，而 `MaskingFilter`
> 跳过的恰恰是保留键 `msg` / `args`。渲染后的 `"password=hunter2"` 既没有
> `password` 键也不是结构体，因此**完全未被脱敏**，却没有任何测试会失败。
> 本 Phase 补齐：过滤器重写 `record.msg` 并清空 `args`（使所有 handler
> 拿到同一份安全文本），两个 formatter 覆盖 `formatException`。

### 1.5 Retention（5 项，Spec `06 §1` / `06 §5`）

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 31 | Access Log 30 days | 提供清理能力 | `RETENTION_DAYS["access"] = 30`；`LogRetentionService.purge` + `scripts/purge_logs.py` | **PASS** | `app/services/log_retention.py`；`tests/test_log_retention.py`（24） |
| 32 | Security Log 180 days | 同上 | `= 180` | **PASS** | `test_each_category_uses_its_own_period` |
| 33 | Operation Log 180 days | 同上 | `= 180` | **PASS** | 同上 |
| 34 | Audit Log 2 years | 同上 | `= 730`（**INTERIM-6-05**：Spec 写 "2 years"，未规定日历年/365×2） | **PASS** | `test_audit_survives_two_years_of_security_cleanup`、`test_audit_is_purged_after_two_years` |
| 35 | Application Log 30 days | 同上 | `= 30` | **PASS** | 同上 |

**清理的边界语义**：严格小于边界（`created_at < cutoff`），
恰好等于边界的行保留 —— 若用 `<=`，保留期实际会变成"29 天 23:59:59"，
一个无法从 Spec 读出、却真实存在的缩短（`test_boundary_is_strictly_older_than_cutoff`）。

**清理的权限语义**：五张表上的 `BEFORE DELETE` 触发器要求事务内显式
`SET LOCAL vctn.retention = 'on'` 才允许删除，且 `SET LOCAL` 是**事务作用域**的
（不污染连接池里的连接）。业务代码**没有**任何删除入口。

**测试覆盖的边界场景**：空类别列表、未知类别（在删除前拒绝）、
类别过滤、`count_expired` 只读、清理后计数归零。

## 2. 额外的安全前置条件（裁判书之外的加密审查）

| 前提 | 判定 | 依据 |
|---|---|---|
| 拒绝必须留痕，且不因业务事务回滚而丢失 | **成立** | 日志与业务事务**彻底分离**：服务层只入内存缓冲，中间件在响应末分片前用独立事务落库。`tests/test_trace_access_log.py::test_handler_can_record_audit_that_gets_persisted` 在端点抛异常（业务回滚）后仍查到审计行 |
| 日志设施故障不得让管理功能不可用 | **成立** | 三层保护：整体超时 5s（asyncpg 默认连接超时 60s，会把 `/health` 存活探针挂死）／连续失败 3 次后熔断 60s／丢弃量计入 `dropped_logs` 且失败计入 `flush_failures`。`tests/test_log_pipeline.py::TestFlushIsBoundedInTime` / `TestCircuitBreaker` |
| 日志设施不得因自身失败而无限增长 | **成立** | 落库期间（`is_flushing()`）产生的日志不投递，切断"失败 → 记 ERROR → 又被收进缓冲"的回路（`test_emit_skips_while_flushing`） |
| 未脱敏数据在内存中停留最短 | **成立** | 脱敏发生在**入缓冲时**（`LogBuffer.add_audit`），而不是落库前；且不修改调用方传入的 `AuditEvent`（`test_original_event_is_not_mutated`） |
| `access_logs` 不替一次性凭据做长期留存 | **成立** | `path` 不含 query string（**INTERIM-6-11**），`test_query_string_is_not_stored` |
| 身份不得跨请求残留 | **成立** | 中间件在请求入口显式 `set_actor_id(None)`，不依赖"上下文本来就是新的"（`test_actor_id_does_not_leak_between_requests`） |

## 3. BLOCKED CHECKS

**无。** 35/35 全部判定为 PASS。

分类说明（本 Phase 未出现 `BLOCKED_BY_DESIGN` / `BLOCKED_BY_ENVIRONMENT`）：

- **DD-08（日志分区）仍未冻结** → 影响的是 `06 §5` / `07 §8` 的
  "**考虑**分区与 retention job"，而裁判书 §Retention 只要求
  "提供清理能力"，本 Phase 已交付（`JUDGMENT-6-01`，见
  `docs/DESIGN-DECISIONS.md §13.1`）。**不构成阻塞**，也**不允许**据此
  把裁判书的范围缩小或扩大。
- 其余未冻结项（DD-01/03/04/05/06/09/10/11/12/13/14/16/18/19/20/21）
  与本 Phase 无依赖关系，未触碰。

### 3.1 本 Phase 登记的 INTERIM / JUDGMENT / FINDING

| 编号 | 内容 | 登记位置 |
|---|---|---|
| INTERIM-6-01 | 表名统一为 `application_logs`（`07 §8` 写作 "application logs"） | `docs/DESIGN-DECISIONS.md §13.3` |
| INTERIM-6-02 | 动作 → 类别的映射表（Spec 未枚举） | 同上 |
| INTERIM-6-03 | 超长值截断到列宽 + `…` 标记 | 同上 |
| INTERIM-6-04 | `application_logs` 入库级别下界 = `INFO` | 同上 |
| INTERIM-6-05 | "2 years" 实现为 730 天 | 同上 |
| INTERIM-6-06 | 落库锚点为响应**末分片之前**（每请求一次额外往返） | 同上 |
| INTERIM-6-07 | 提供清理入口但不内建调度器（调度属部署决策） | 同上 |
| INTERIM-6-08 | 熔断参数 5s / 3 次 / 60s | 同上 |
| INTERIM-6-09 | 自由文本中的令牌整体脱敏（比 `06 §4` 的"前 6 字符"更严） | 同上 |
| INTERIM-6-10 | `security_logs.reason` 从 `after_data` 提升为独立列 | 同上 |
| INTERIM-6-11 | `access_logs.path` 不含 query string | 同上 |
| INTERIM-6-12 | `operator_id` 经 ContextVar 传递，中间件不解析令牌 | 同上 |
| INTERIM-6-13 | `LOG_MODELS` 单一清单（键 = 表名），与 `RETENTION_DAYS` 一一对应 | 同上 |
| JUDGMENT-6-01 | DD-08 未冻结 → 不分区，交付普通表 + 清理能力 | `docs/DESIGN-DECISIONS.md §13.1` |
| FINDING-6-01 | 分类失败时审计主表**仍写**（否则整批日志一起丢） | `docs/DESIGN-DECISIONS.md §13.4` |
| FINDING-6-02 | 包 `__init__` 重导出遮蔽同名子模块（已修复 + 回归测试） | `docs/DESIGN-DECISIONS.md §13.6`、本文件 §5.1 |

## 4. 门禁与迁移证据

| 门禁 | 命令 | 结果 |
|---|---|---|
| Lint | `ruff check .` | `All checks passed!` |
| Format | `ruff format --check .` | `185 files already formatted` |
| Types | `mypy`（`--strict`，`app`） | `Success: no issues found in 89 source files` |
| Schema | `alembic check` | `No new upgrade operations detected.` |
| Tests | `pytest -q` | **`955 passed in 779.95s`（EXIT=0）** |

测试总数从 Phase 5 收尾时的 **805** 增至 **955**，增量 **+150** 与 §5 列出的
本 Phase 新增用例数**完全一致**，说明没有靠删改既有用例换取绿灯。

**手工端到端验证**（保留期能力不只存在于测试里）：

```console
$ python scripts/purge_logs.py --dry-run
[dry-run] access: 0 row(s) expired
[dry-run] application: 0 row(s) expired
[dry-run] audit: 0 row(s) expired
[dry-run] operation: 0 row(s) expired
[dry-run] security: 0 row(s) expired

$ python scripts/purge_logs.py
[purged] access: 0 row(s), cutoff=2026-08-26T01:22:21+00:00
[purged] application: 0 row(s), cutoff=2026-08-26T01:22:21+00:00
[purged] audit: 0 row(s), cutoff=2024-09-25T01:22:21+00:00
[purged] operation: 0 row(s), cutoff=2026-03-29T01:22:21+00:00
[purged] security: 0 row(s), cutoff=2026-03-29T01:22:21+00:00
[done] total deleted = 0
```

写入路径（`SET LOCAL` + `DELETE` + `COMMIT`）真的通过了 append-only 触发器；
边界日期也印证了保留期：access/application = 30 天，operation/security = 180 天，
audit = 730 天。

**迁移**：`alembic/versions/20260925_0845_phase6_dd08_log_tables.py`
（`revision='phase6_dd08'`，`down_revision='phase5_dd24'`）。

```text
五张表 + 索引
+ 三个 plpgsql 函数：
    vctn_reject_log_update()     -- 无条件拒绝 UPDATE
    vctn_guard_log_delete()      -- 仅允许 vctn.retention = 'on' 的 DELETE
    vctn_guard_log_truncate()    -- 仅允许 vctn.retention = 'on' 的 TRUNCATE
+ 每张表三个触发器（共 15 个）
```

`down_revision` 只指向 `phase5_dd24`（不叠加未提交的中间迁移）；
迁移链已用 `alembic downgrade phase5_dd24 && alembic upgrade head` 验证可往返，
`alembic check` 无残差。

**`vctn.retention` 为何用 `'on'` 而不是 `true`**：`current_setting(name, true)`
在**未设置**时返回 NULL，而守卫判定写作 `IS DISTINCT FROM 'on'` ——
于是"忘记设置"与"设置成别的值"都落到拒绝分支（fail-closed）。

## 5. 测试覆盖

| 文件 | 用例数 | 类型 |
|---|---|---|
| `tests/test_masking_text.py` | 29 | 单元（无需数据库） |
| `tests/test_log_classification.py` | 21 | 单元 |
| `tests/test_log_pipeline.py` | 30 | 单元 |
| `tests/test_log_repository.py` | 33 | 集成（真实 PostgreSQL） |
| `tests/test_log_retention.py` | 24 | 集成 |
| `tests/test_trace_access_log.py` | 13 | 集成（端到端：请求 → 缓冲 → 独立事务 → 数据库行） |
| **合计（本 Phase 新增）** | **150** | |

关键反证用例（"如果实现错了会怎样"）：

- `test_naive_overlong_write_would_have_failed`：不截断确实会抛数据库异常
  → 证明截断不是美化，而是堵住一条抗审计通道；
- `test_truncate_without_retention_intent_is_rejected` /
  `test_delete_without_retention_intent_is_rejected`：append-only 是**数据库**
  强制的，不是"ORM 里没写 update 方法"的约定；
- `test_unclassified_action_keeps_the_audit_row`：分类失败不会连带丢掉审计主记录；
- `test_hanging_database_is_abandoned_after_the_timeout`：数据库"丢包"时
  `/health` 不会被挂住 60 秒；
- `TestPackageNamespaceDoesNotShadowSubmodules`：钉住 FINDING-6-02 的成因。

**对既有用例的影响**：`tests/conftest.py` 新增 autouse 夹具 `isolate_log_flush`，
把日志落库替换为"吞掉写入"的会话替身。理由：每个 HTTP 请求结束时中间件都会
落库，若走默认提供者，测试期的不可达数据库会让**每个请求**产生一次连接失败
加一条 ERROR 堆栈，既污染输出又污染 `flush_failures` 这个被断言的计数器。
需要真实落库的用例自行注入（`test_trace_access_log.py::flush_into_session`）。
该夹具只影响测试进程，不改变产品行为。

### 5.1 本 Phase 的 FAIL → 修复 → 重新 Verification 记录

完整测试运行暴露了 **2 个 FAIL**，且**两个都指向同一处根因**：

```text
FAILED tests/test_log_classification.py::TestClassify::test_unknown_action_raises_instead_of_falling_back
FAILED tests/test_log_repository.py::TestDispatch::test_unclassified_action_keeps_the_audit_row
AttributeError: 'function' object at app.audit.classify has no attribute 'SECURITY_ACTIONS'
```

- **根因**：`app/audit/__init__.py` 重导出了 `classify` 函数。
  `classify` 同时是**子模块名**与**其中的函数名**，重导出使
  `app.audit.classify` 这个属性由模块变成函数 —— 于是所有按点号字符串定位
  的目标（`pytest` 的 `monkeypatch.setattr("app.audit.classify.X", ...)`）解析失败。
  该缺陷只在特定 import 顺序下暴露：`sys.modules` 里仍是模块，
  `importlib.import_module` 一切正常，只有 `getattr` 路径受影响。
- **修复**：包 `__init__` 不再重导出 `classify`（保留 `LogCategory` 与三个动作集合），
  并在模块文档中写明原因；同时新增
  `TestPackageNamespaceDoesNotShadowSubmodules` 把它钉成**回归测试**
  （含一条真实复现失败用法的用例）。
- **重新验证**：受影响的两个文件复跑 54 passed；随后执行**完整**门禁。

**FINDING-6-02**（已修复）登记于 `docs/DESIGN-DECISIONS.md §13.6`。

## 6. Phase 边界（本 Phase 未做，且不应做）

- **DD-08 分区 / 归档到对象存储**：未冻结 → 不实现（`JUDGMENT-6-01`）。
- **日志查询 / 导出 API**（`08` 未列相关端点）：属新增业务能力，不做。
- **调度器 / 后台任务框架**：不由应用进程承担（`INTERIM-6-07`）。
- **日志加密存储**：Spec 未要求；`13 §2` 的密钥清单中无日志密钥。
- **Phase 7 字典与系统参数**：`MFA_REQUIRED_DEFAULT` 的迁入在 Phase 7 进行，
  本 Phase 不建参数表（避免与 Phase 7 交付重叠成两套参数机制）。

## 7. 结论

**Verification 006：PASS（35/35，0 BLOCKED）。**

判定过程严格执行了 `AGENTS.md` 的
`IMPLEMENT → VERIFY → FAIL → 定位根因 → 修复 → 重新 VERIFY`：

- 首次完整门禁暴露 2 个 FAIL，根因同一处（`FINDING-6-02`），已修复并补回归测试；
- 修复后重跑受影响文件（54 passed），再执行**完整**门禁作为最终证据（见 §4/§5）。

Phase 6 同时关闭了一个**长期存在但此前无裁判项命中**的真实缺口：
Phase 2~5 期间 `deps.py` 用 `NullAuditRecorder` 构造全部服务，
所有审计事件只到内存为止（详见 `docs/DESIGN-DECISIONS.md §13.5`）。
本次不仅补上落库，还补上了**消息正文**的脱敏 —— 此前
`06 §4` 的五条规则在最常见的日志路径上完全不生效。
