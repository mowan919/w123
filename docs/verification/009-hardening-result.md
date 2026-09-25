# Verification 009 — Hardening 执行结果

- 裁判：`docs/verification/009-hardening.md`（12 项）
- 阶段：`PHASES.md` Phase 9 — Hardening
- 日期：2026-09-25
- 提交：`feat: complete phase 9 hardening and close finding-8-01`

| 项 | 值 |
|---|---|
| 结论 | **PASS**（12/12 检查通过；0 项 BLOCKED；0 项 NOT RUN） |
| 门禁 | ruff `All checks passed!` / format `219 files already formatted` / mypy `Success: no issues found in 108 source files` / alembic `No new upgrade operations detected.` / pytest **`1208 passed`** |
| 增量 | Phase 8 结束为 1156 例 → 现 **1208 例（+52）**，零告警 |

---

## 1. 逐项判定

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 1 | 权限缓存有失效机制 | 若存在权限缓存，必须有失效机制 | **不存在任何缓存**：`PermissionContractService` 每次调用实时计算 | **PASS** | `tests/test_hardening.py::TestNoStalePermission::test_contract_service_declares_no_cache`（用源码断言钉住"不得出现缓存痕迹"）；`docs/DESIGN-DECISIONS.md §15.7` |
| 2 | 权限变更无明显 stale permission | 变更后立即可见，无需失效动作 | 同一会话内授予页面后，下一次契约构建即包含它 | **PASS** | `::test_grant_change_is_visible_within_a_few_calls`；Phase 8 的 `TestImmediateEffect`（3 例） |
| 3 | 关键写操作具备幂等策略（适用时） | 重复提交不产生额外副作用 | 会话撤销二次调用返回 `False` 且不改写原因（DD-11 方案 A） | **PASS** | `tests/test_hardening.py::TestIdempotency::test_revoking_an_already_revoked_session_succeeds`；`app/repositories/session.py` |
| 4 | 并发更新有保护 | 并发下的关键写入不得相互覆盖 / 静默丢失 | `rotate_tokens` 为 **CAS 条件更新**：持有旧值的第二个写入者匹配 0 行；退役哈希留档用 `ON CONFLICT DO NOTHING`，并发下必然重复也不抛错 | **PASS** | `::TestConcurrencyProtection::test_token_rotation_is_a_compare_and_swap`、`::test_retiring_the_same_token_twice_does_not_raise`、`::test_full_replacement_makes_last_write_wins_safe`。边界见 §3 |
| 5 | 登录有必要的 rate limit | 登录尝试按主体与来源受限 | 新增 `app/core/rate_limit.py`；登录按**用户名**（10/分）与**来源 IP**（30/分）双维计数，超限 429/429001 | **PASS** | `tests/test_rate_limit.py::TestLoginEndpointLimit`（4 例） |
| 6 | MFA 有必要的 rate limit | MFA 校验尝试受限 | `POST /auth/mfa/verify` 按来源 IP 限流（20/分），超限 429/429001 | **PASS** | `tests/test_rate_limit.py::TestMfaEndpointLimit::test_verify_is_rate_limited` |
| 7 | 错误响应不泄漏内部异常 | 500 响应不含异常消息 / 类型 / 堆栈 | `handle_unexpected_error` 返回统一信封；422 丢弃 `input` 原文（否则登录场景回显明文口令） | **PASS** | `tests/test_hardening.py::TestErrorMasking`（3 例） |
| 8 | Secret 不进入日志 | 密钥类字段在日志中不可见 | 修复 **FINDING-9-01** 后，`password=` / `password:` / `password='..'` / **JSON** 四种形状全部脱敏且幂等 | **PASS** | `::TestSecretNeverReachesLogs`（2 例）；`app/core/masking.py` |
| 9 | Migration 可重复部署 | 重复部署无副作用，且模型与迁移不漂移 | `alembic check` → `No new upgrade operations detected.`；每个有操作的 `upgrade()` 均有对应 `downgrade()` | **PASS** | `::TestMigrationSafety`（2 例）。边界见 §3 |
| 10 | 数据库关键索引存在 | 关键查询路径有索引，软删除感知唯一为 partial index | 实查 **82** 条索引、**11** 条 partial index（含 7 张业务表的软删除感知唯一） | **PASS** | `::TestDatabaseGuarantees::test_soft_delete_unique_indexes_are_partial`；`scripts/db_inspect.py`（只读巡检） |
| 11 | FK 行为符合逻辑删除设计 | 不得存在会绕过逻辑删除的级联物理删除 | CASCADE 外键**白名单**：当前仅 `mfa_challenges → admin_users` 一条（瞬态挑战），且被其它 NO ACTION 外键挡住而不可触发 | **PASS** | `::TestDatabaseGuarantees::test_no_cascade_foreign_keys` |
| 12 | 安全审查无高危未解决项 | 无 P0 / 高危未解决项 | 本阶段修复 2 个真实缺陷（FINDING-9-01 / 9-02），关闭 1 个交付缺口（FINDING-8-01）；未发现新的 P0 / 高危项 | **PASS** | `docs/DESIGN-DECISIONS.md §16.5 / §16.6 / §16.7 / §16.11` |

---

## 2. 裁判之外必须自证的前提

裁判 12 项只描述"要做的事"。以下 5 项是"做得对不对"的必要条件：

| 项 | 自证内容 | 证据 |
|---|---|---|
| A | **限流在校验凭据之前**：成功的登录也要消耗配额，否则它只挡住"已经失败的请求"，对攻击者零成本 | `test_successful_login_also_consumes_quota` |
| B | **限流键不含原始主体**：Redis 会被运维查看 / 进慢日志，明文用户名等于一份攻击目标清单 | `TestKeyBuilding::test_key_never_carries_the_raw_subject`；真 Redis 上 `exists(key)` 与 `ttl(key) > 0` |
| C | **限流键必有 TTL**：否则一次崩溃留下的孤儿键会永久封禁某个主体 | `TestRedisBackend::test_real_redis_counts_and_sets_ttl`（打真实 Redis） |
| D | **429 文案不带任何信息**：不说是哪个维度超限，否则等于把绕行路线画出来 | `TooManyRequestsError` docstring；`test_wrong_password_is_also_limited` 断言用户名不出现在响应里 |
| E | **中间件只补缺、不覆盖**：端点设置的 `Cache-Control` 必须保留 | `TestSecurityHeaders::test_existing_headers_are_not_overwritten` |

---

## 3. BLOCKED CHECKS

**无。** 既无 `BLOCKED_BY_ENVIRONMENT`，也无 `BLOCKED_BY_DESIGN`。

### 两处**验证边界**（不是 BLOCKED，是"此处不越界"）

**(a) 并发（裁判 #4）**
本阶段证明的是**保护机制存在且生效**（CAS 使第二个写入者匹配 0 行），
**不是**多连接竞态压测 —— `db_session` 夹具把每个用例包在一个事务里并回滚，
两任务的"并发"会共用同一条连接从而被串行化，
那样跑出来的"并发测试"是假的。真正的竞态压测需要独立连接池与已提交的数据。

**(b) 迁移回滚（裁判 #9）**
已验证**正向幂等**、**无漂移**、**回滚路径存在**；
**未**执行完整的 `downgrade base → upgrade head` 循环 ——
远端 PostgreSQL 是共享实例，跑降级会抹掉全部数据。
该循环应在独立的临时库上验证。

### 本 Phase 登记项

| 编号 | 内容 | 状态 |
|---|---|---|
| INTERIM-9-01 | 限流阈值（**DD-10 未冻结**）→ 全部做成配置项 | 已登记 |
| INTERIM-9-02 | 限流键命名（`rl:v1:...`，**DD-03 未冻结**，本登记只覆盖限流键） | 已登记 |
| JUDGMENT-9-01 | Redis 不可用时 fail-open（主防线是 DB 上的账号锁定） | 已登记 |
| JUDGMENT-9-02 | HSTS 默认不下发（"下发后难以撤回"的承诺） | 已登记 |
| JUDGMENT-9-03 | CASCADE 外键用白名单而非一律禁止 | 已登记 |
| **FINDING-9-01** | JSON 形状的密钥未被脱敏 | **已修复** |
| **FINDING-9-02** | PUT 无法做部分更新（省略字段被当成清空） | **已修复** |
| **FINDING-8-01** | 组织实体 CRUD 的 HTTP 面缺失 | **已关闭** |

---

## 4. 交付清单

**新增**

- `app/core/rate_limit.py` —— 固定窗口限流器（Redis / 内存双后端、fail-open 可配）
- `app/middleware/security_headers.py` —— 安全响应头纯 ASGI 中间件
- `app/api/v1/endpoints/users.py` —— `08 §4` 的 7 条端点（**FINDING-8-01**）
- `app/api/v1/endpoints/departments.py` —— `08 §6` 的 4 条端点（**FINDING-8-01**）
- `app/api/v1/endpoints/roles.py` —— `08 §7` 的 3 条实体端点（**FINDING-8-01**）
- `scripts/db_inspect.py` —— 只读数据库巡检（索引 / 外键 / partial index）
- `tests/test_rate_limit.py`（17 例）、`tests/test_hardening.py`（22 例）、`tests/test_organization_api.py`（18 例）

**修改**

- `app/core/masking.py` —— 修复 FINDING-9-01（JSON 形状密钥脱敏）
- `app/core/errors.py` —— 新增 `TooManyRequestsError`（429001 + `Retry-After`）
- `app/core/config.py` —— 限流与安全头配置项
- `app/api/v1/endpoints/auth.py` —— 登录与 MFA 校验接入限流
- `app/api/deps.py` —— 新增 `UserServiceDep` / `RoleServiceDep` / `DepartmentServiceDep`
- `app/services/authorization.py` —— 新增 `USER_MANAGE` / `DEPARTMENT_MANAGE`
- `app/services/user.py` / `department.py` —— 公开三态哨兵 `UNSET`
- `app/main.py` —— 挂载 `SecurityHeadersMiddleware`
- `tests/conftest.py` —— `isolate_rate_limiter`（内存后端）与 `real_redis_client`（真 Redis）

**迁移**：本 Phase **无**新增迁移（`alembic check` 确认无漂移）。

---

## 5. 门禁与复现

```powershell
.\.venv\Scripts\ruff.exe check .            # All checks passed!
.\.venv\Scripts\ruff.exe format --check .   # 219 files already formatted
.\.venv\Scripts\mypy.exe                    # Success: no issues found in 108 source files
.\.venv\Scripts\alembic.exe check           # No new upgrade operations detected.
.\.venv\Scripts\python.exe -m pytest -q     # 1208 passed
.\.venv\Scripts\python.exe scripts\db_inspect.py   # 只读巡检（需 PYTHONPATH=.）
```

---

## 6. 本 Phase 发现并修复的缺陷

| # | 缺陷 | 后果 | 修复 |
|---|---|---|---|
| FINDING-9-01 | `_SECRET_PAIR_RE` 要求键名后紧跟 `:` / `=`，而 JSON 里键名后是引号 → `{"password": "..."}` **整条明文落库** | 脱敏漏掉了结构化日志**最常见**的形状 | 键名与冒号、冒号与值之间均允许可选引号；值取到引号/空白/分隔符为止。已验证四种形状且幂等 |
| FINDING-9-02 | `PUT /users/{id}` 与 `PUT /departments/{id}` 把 DTO 默认值 `None` 原样透传 | 非全局范围下 403（改不动任何字段）；全局范围下**静默把用户移出部门 / 把部门移到根**，无任何报错 | 用 `model_fields_set` 判断客户端实际提交的字段，未提交的显式传 `UNSET`（服务层本就支持三态，缺的是端点分派） |
| FINDING-8-01 | `08 §4/§6/§7` 冻结的组织实体 CRUD **只有服务层、没有 HTTP 端点** | 系统无法经 API 创建 / 管理部门、角色、用户 | 补交付 14 条端点，绑定 `USER_MANAGE` / `DEPARTMENT_MANAGE` / `ROLE_MANAGE` |

---

## 7. 结论

`docs/verification/009-hardening.md` 的 **12 项全部 PASS**，0 项 BLOCKED。

两处验证边界（并发压测、迁移降级循环）已如实记录，未被当作 PASS 蒙混。
FINDING-8-01 已关闭 —— 此前"后端全部做完"不成立的主要缺口。
