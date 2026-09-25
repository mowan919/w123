# Verification 010 — Final Acceptance 结果

- 裁判书：`docs/verification/010-final-acceptance.md`
- 阶段文档：`docs/agent/PHASE-010-FINAL.md`
- 判定时间：2026-09-25
- 判定对象：**当前代码**（不是历史快照）—— 按 `PHASE-010-FINAL.md` 的
  "阅读全部 Spec、执行全部 Verification"，本文件对 001~009 的结论做一次
  **串联复核**，并补上"只在串起来之后才会暴露"的那一类缺陷。

## 0. 结论

| 类别 | 项数 | PASS | FAIL | BLOCKED |
|---|---|---|---|---|
| Build | 4 | 4 | 0 | 0 |
| Functional | 12 | 12 | 0 | 0 |
| Security | 8 | 8 | 0 | 0 |
| Permission Matrix | 5 | 5 | 0 | 0 |
| **合计** | **29** | **29** | **0** | **0** |

**最终状态：PASS**

> 本次验收发现并修复了 **1 处交付缺口**（FINDING-10-01：`08 §8` 冻结的
> 审计 / 链路读端点一条都不存在）与 **1 处文档与实现不符**（FINDING-10-02）。
> 两者均已在本次判定**之前**修复并由新增测试钉住；判定结论依据的是修复后的代码。

---

## 1. Build

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| B-1 | Backend can start | 进程启动完成，无启动期异常 | `uvicorn app.main:app` 在 `127.0.0.1:8123` 启动完成，日志 `Application startup complete.` | **PASS** | 实跑输出（2026-09-25 06:52） |
| B-2 | Database migration succeeds | `alembic upgrade head` 成功且无漂移 | `alembic current` = `phase7_dict (head)`；`upgrade head` 为 no-op；`alembic check` → `No new upgrade operations detected.` | **PASS** | 实跑；另见 `tests/test_hardening.py::test_alembic_sees_no_drift` |
| B-3 | Redis connection succeeds | 连通 | `check_redis()` 返回正常；启动日志 `dependency_ready dependency=redis` | **PASS** | 实跑 + `/api/v1/admin/health/redis` → `{"status":"up"}` |
| B-4 | Health check succeeds | liveness / readiness 探针可用 | `/health` → 200；`/api/v1/admin/health/ready` → 200 `{"database":{"status":"up"},"redis":{"status":"up"}}` | **PASS** | 实跑（4 个探针全部 200） |

### B-1/B-4 的实跑记录

```text
GET /health
{"code":0,"message":"success","data":{"status":"ok","app":"VCTN","env":"local","version":"0.1.0"}}

GET /api/v1/admin/health/ready
{"code":0,"message":"success","data":{"status":"ready","checks":{"database":{"status":"up"},"redis":{"status":"up"}}}}

GET /api/v1/admin/health/db     → {"component":"database","status":"up"}
GET /api/v1/admin/health/redis  → {"component":"redis","status":"up"}

GET /api/v1/admin/users  （未认证）
HTTP/1.1 401 Unauthorized
x-trace-id:    6e1475a7ce4946038cf66d80b1a1fc31
x-request-id:  bcfd76b8daf34a83be7f6ab99e8dcae3
x-content-type-options: nosniff
x-frame-options: DENY
referrer-policy: no-referrer
cache-control: no-store
{"code":401001,"message":"认证失败或登录状态已失效","data":null}
```

最后一段同时证明了三件事：**认证生效**（401）、**Trace 头传播**（`06 §3`）、
**安全响应头下发**（Phase 9）。

---

## 2. Functional

判定口径：**不是**重跑 001~008 的全部裁判项（那 9 份结果文件仍然有效），
而是核对"每个业务域是否都有**可调用的 HTTP 面** + **已 PASS 的裁判**"。
这正是本次唯一一处 FAIL 被抓到的方式（见 FINDING-10-01）。

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| F-1 | Organization | `08 §6` 的 4 条端点可用 | `/departments/tree`、`POST /departments`、`PUT /departments/{id}`、`POST /departments/{id}/disable` 全部存在 | **PASS** | `tests/test_organization_api.py::TestRouteSurface`（FINDING-8-01 补交付）；`001-organization-user-result.md` PASS |
| F-2 | User | `08 §4` 的 7 条端点可用 | 逐条存在并绑定 `USER_MANAGE` | **PASS** | `tests/test_organization_api.py`；`001` PASS |
| F-3 | Role | `08 §7` 实体 3 条 + 授权 6 条 + 数据范围 2 条 | 11 条全部存在 | **PASS** | `tests/test_organization_api.py`、`tests/test_role_permission_api.py`；`002` PASS |
| F-4 | Permission | 权限资源定义 8 条端点 + 有效权限引擎 | `/admin/permission-resources*` 8 条存在；`GET /auth/permissions` 输出 `09 §2` 七段契约 | **PASS** | `008-dynamic-permission-result.md` 11/11 PASS |
| F-5 | Authentication | `08 §3` 的 10 条端点 | 登录 / MFA 校验 / refresh / logout / me / permissions / MFA 自我管理全部存在 | **PASS** | `003-authentication-result.md` PASS |
| F-6 | Session | `08 §5` 2 条 + `/users/{id}/sessions*` 2 条 | 4 条存在；在线状态 / 单踢 / 全踢可用 | **PASS** | `004-session-result.md` 15/15 PASS |
| F-7 | MFA | setup / enable / disable / verify | 4 条存在；Secret 加密存储、策略解析、挑战机制就位 | **PASS** | `005-mfa-result.md` 13/13 PASS |
| F-8 | Logs | 五类日志落库 **且** 可查询 | 落库（006 PASS）+ **`GET /audit/logs` / `GET /audit/logs/{id}` 本次补交付** | **PASS** | `tests/test_log_query_api.py`（13 例）；见 §6 FINDING-10-01 |
| F-9 | Audit | `06 §2` 15 字段、append-only **且** 可查询 | append-only 由数据库触发器强制；查询端点同上 | **PASS** | `006-logging-audit-result.md` 35/35 PASS + 本次补交付 |
| F-10 | Trace | `X-Trace-ID` / `X-Request-ID` 贯穿 **且** 可回放 | 中间件传播（实跑验证）+ **`GET /traces` / `GET /traces/{traceId}` 本次补交付** | **PASS** | 实跑响应头；`tests/test_log_query_api.py::TestTraceHttp` |
| F-11 | Dictionary | `05 §4` 9 条管理端点 + 1 条公开查询 | 全部存在 | **PASS** | `007-dictionary-result.md` 18/18 PASS |
| F-12 | Dynamic Permission | `09 §2` 七段契约 + 资源 CRUD HTTP 面 | pages / menus / buttons / apis / fields / data_scope / permission_version 全部输出 | **PASS** | `008-dynamic-permission-result.md` 11/11 PASS |

### 2.1 路由面对账（本次新增的全量核对）

`create_app().openapi()` 共 **69** 条 operation（不含 `HEAD` / `OPTIONS`）：

```text
/api/v1/admin   57 条
    health                4   （/health、/ready、/db、/redis）
    users                 9   （08 §4 的 7 条 + /users/{id}/sessions* 2 条）
    departments           4   （08 §6）
    sessions              2   （08 §5）
    roles                12   （08 §7：实体 3 + 授权 6 + 数据范围 2 + /roles 2）
    permission-resources  8   （DD-20 §5.1.1）
    dicts                 9   （08 §9）
    params                5   （05 §5；路径属 INTERIM-7-04）
    audit + traces        4   （08 §8 —— 本次补交付）

/api/v1/auth    11 条   （08 §3）
/api/v1/dicts    1 条   （公开字典查询，05 §4）

（`/docs`、`/openapi.json`、根 `/health` 不在 OpenAPI schema 内）

54 条路径 / 69 个 operation（同一路径上有多个方法，故两者不等）。
分桶按**路径前缀**，因此 `/users/{id}/sessions*` 计入 `users` 而非 `sessions`。
```

其中 `audit/logs*` 与 `traces*` 这 4 条是**本次**补上的 —— 在此之前
`08 §8` 的冻结清单与实跑路由面相差 4 条，而前面 9 个阶段的验收**没有一项**
会发现这件事（详见 §6）。

---

## 3. Security

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| S-1 | API authorization | 每个受保护 API 都经后端 API 权限校验，禁止仅靠菜单/按钮隐藏 | 声明式绑定 `require_api_permission`（DD-20 §5.1.3）；无权限 → 403001；**新增全路由护栏**：任何未声明授权的管理端点都会让测试失败 | **PASS** | `tests/test_organization_api.py::TestAccessControl`、`tests/test_permission_matrix.py`、`tests/test_route_authorization_guard.py`（5 例） |
| S-2 | Data scope | Department Admin = 本部门 + 子部门；范围外**看不见** | 列表下推到 SQL（范围外目标不在结果里）；单读 403 且留 FAILURE 审计 | **PASS** | `TestDepartmentAdmin::test_scope_is_department_plus_children`；`test_cannot_read_target_outside_scope` |
| S-3 | SUPER_ADMIN protection | 不可被其他管理员禁用 / 删除 / 改角色 | `POST /users/{super}/disable` → 403001（即使调用者持有管理权限位） | **PASS** | `TestSuperAdmin::test_cannot_be_disabled_by_another_admin`；`tests/test_authorization.py`；`tests/test_user_service.py::test_department_admin_cannot_disable_super_admin` |
| S-4 | Password policy | 复杂度校验 + 历史不可重用 + 重置后强制改密 | 弱口令被拒；历史重用被拒且有上限；创建/重置后 `must_change_password=True` | **PASS** | `test_weak_password_is_rejected`、`test_password_history_rejects_reuse`、`test_password_history_is_capped` |
| S-5 | Account lockout | 连续失败达阈值后锁定 | 锁定后**正确口令也被拒**；锁定不改 `status`（`status` 与"临时锁定"是两个维度） | **PASS** | `test_locked_account_rejects_correct_password_within_lockout`、`test_lockout_does_not_flip_status_to_locked` |
| S-6 | Session revocation | 撤销后令牌立即不可用；单踢 / 全踢 | Access 与 Refresh 双双失效；重复撤销语义幂等且不改写首次原因；审计留痕 | **PASS** | `test_revoke_invalidates_access_and_refresh`、`test_revoke_is_idempotent_and_keeps_first_reason`、`test_revoke_audited`、`test_revoke_all_*` |
| S-7 | MFA | 策略要求即强制二次验证；Secret 只在 setup 流出一次 | 策略解析（含系统参数默认值）；Secret 加密存储；挑战有一次上限 | **PASS** | `005-mfa-result.md`；`tests/test_mfa_policy.py`、`tests/test_mfa_crypto.py` |
| S-8 | Sensitive masking | phone / email / token / password / MFA Secret 规则生效 | 五类规则全覆盖且幂等；JSON 形状的密钥也命中（Phase 9 修复） | **PASS** | `tests/test_masking_text.py`（含 `test_password_pair_never_logged`、`test_jwt_never_logged`）；`tests/test_hardening.py::TestMasking` |

### 3.1 纵深防御抽样（实跑，非单测）

未认证访问 `/api/v1/admin/users` → **401**（不是 404，路径存在性不因认证状态改变）。
有权限位但目标在范围外 → **403 + FAILURE 审计**。
无权限位 → **403001**。
`Cache-Control: no-store` 保证权限契约不被缓存留存（`09 §7` 立即生效的前提）。

---

## 4. Permission Matrix

裁判书要求至少验证五类主体。本次**全部在 HTTP 层**跑通
（真实登录 → 真实请求 → 真实数据范围），
新增 `tests/test_permission_matrix.py`（11 例）。

| # | 主体 | CHECK | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| P-1 | SUPER_ADMIN | 全局可见、无需 `*_MANAGE` 权限位即可访问受保护端点、不可被其他管理员禁用 | `GET /users` 同时看到范围内与范围外目标；`users`/`roles`/`departments` 全部 200；禁用超管 → 403001 | **PASS** | `TestSuperAdmin`（3 例） |
| P-2 | Department Admin | 本部门 + 子部门；范围外不可见 | `USER_TARGET_IN` 在结果里，`USER_TARGET_OUT` 不在；单读范围外 → 403 | **PASS** | `TestDepartmentAdmin`（2 例） |
| P-3 | Normal User | 无管理权限 → 拒绝；仍可读自己的权限契约 | `GET /users`、`GET /roles` → 403001；`GET /auth/permissions` → 200 且 `pages`/`apis` 为空 | **PASS** | `TestNormalUser`（2 例） |
| P-4 | 多角色用户 | 权限**取并集**（`00 §1#2`）；数据范围**取并**（DD-19） | 两个角色各持一半权限 ⇒ 两个端点都能访问；`SELF ∪ DEPARTMENT_CHILDREN` 覆盖下级部门 | **PASS** | `TestMultiRoleUser`（2 例） |
| P-5 | 有继承角色用户 | 子角色**自身无授权**，权限来自父角色（`03 §4`） | `GET /users` → 200；契约中 `inherited_role_ids` 含父角色且**不含**自己的直接角色 | **PASS** | `TestInheritedRoleUser`（2 例） |

### 4.1 为什么必须在 HTTP 层再跑一遍

前面 9 个阶段已分别验证过角色 CRUD、数据范围、继承展开、多角色求并、
API 权限绑定。但那些是**分层验证**：每层单独成立，不等于**串起来**还成立。

一次真实请求要穿过四道门：

```text
认证 → 路由级 API 权限 → 服务层授权 → 数据范围下推（SQL）
```

其中任何一道装反了（例如路由级放行、但服务层用了错误的 scope），
分层测试都不会红 —— 因为分层测试各自注入了自己那一层的**正确输入**。
P-1~P-5 全部走真实登录 + 真实 HTTP，因此**四道门的串联顺序**也在断言范围内。

### 4.2 P-4 / P-5 为什么必须是两个不同的主体

继承展开发生在有效权限引擎（`EffectivePermissionService`），
多角色求并发生在数据范围解析（`DataScopeResolver`）——
**两条不同的代码路径**。用同一个用例验证两者，会掩盖
"其中一条没接上"的缺陷。

---

## 5. 门禁

```text
ruff check   .                     All checks passed!
ruff format  --check .             228 files already formatted
mypy                               Success: no issues found in 112 source files
pytest -q -W error::Warning        1242 passed in 1423.27s（0:23:43，零告警）
```

- `-W error::Warning`：任何告警都会变成失败，因此"通过了但有一堆
  DeprecationWarning"这种情况不会混进 PASS。
- 1242 = 1213（Phase 9 结束时）+ 29（本次新增：
  `test_log_query_api.py` 13 例、`test_permission_matrix.py` 11 例、
  `test_route_authorization_guard.py` 5 例）。
- 门禁是在**修复后**的代码上跑的（并非"先判 PASS 再修"），
  且在最终工作树状态下整轮重跑，不是抽样。
- 全 ID 收集数已核对：`pytest --collect-only` → **1242**，与实跑数一致
  （防止"有 skip / deselect 让数字对不上"）。

---

## 6. 本次发现并修复的问题

### 6.1 FINDING-10-01 —— `08 §8` 的审计 / 链路读端点一条都没有（**交付缺口**）

`08 §8` 冻结：

```text
GET /audit/logs
GET /audit/logs/{id}
GET /traces
GET /traces/{traceId}
```

实际路由面：**0 条**。

**根因**：Phase 6 的裁判（`006-logging-audit.md`，35 项）**全部是落库判定**
——五类日志写不写得进、字段齐不齐、保留期对不对——没有任何一项问
"能不能把它们读出来"。于是那次 PASS 不会暴露"日志只进不出"。

这是**同一类缺口的第二次发生**（第一次是 FINDING-8-01：
Users / Departments / Roles 实体 CRUD 缺 HTTP 面）。共同根因：

> **裁判项只判服务层，于是"HTTP 面不存在"永远判不出来。**

**修复**：

- `app/repositories/log_query.py`（读侧仓储）、
  `app/services/log_query.py`（归一化 + 成功审计）、
  `app/api/v1/endpoints/audit_logs.py`（4 条端点）、
  `tests/test_log_query_api.py`（13 例）。
- 新增两个权限位 `AUDIT_READ` / `TRACE_READ`（INTERIM-10-02）
  与两个审计动作 `AUDIT_LOG_READ` / `AUDIT_TRACE_READ`（INTERIM-10-03）。

**防再犯网**：`tests/test_log_query_api.py::TestRouteSurface`
同时钉住"四条必须存在"与"不得有清单之外的审计/链路端点"。

登记：`docs/DESIGN-DECISIONS.md §17.2`。

### 6.2 FINDING-10-02 —— 文档与实现不符（改文档，不改实现）

`endpoints/users.py::get_user` 的 docstring 写着"范围外用户按不存在处理
（不泄露存在性）"，但 `UserService.get` 对范围外目标抛
`PermissionDeniedError` → **403**。

裁定：**403 是正确的，改的是文档**。403 附带 FAILURE 审计，
留下"谁试图访问谁"的取证记录；改成 404 会让这类探测在审计里消失。
列表与单读表现不同是**有意的**：列表防数据外泄，单读留下取证。

登记：`docs/DESIGN-DECISIONS.md §17.3`。

### 6.3 DEBT-10-01（技术债，不计入 FAIL）—— 18 个 operation 把授权绑在服务层

S-1 判 PASS 时的全路由扫描顺带发现：Phase 5 的会话端点与 Phase 7 的
字典 / 参数端点**没有路由层**的声明式绑定，授权发生在**服务层**
（`assert_can_manage_sessions` / `assert_can_manage_dicts` /
`assert_can_manage_params`，三者最终都走 `assert_api_permission`）。

判定：**`08 §10` 满足**（后端确实做了 API 权限校验），
因此**不计为 FAIL**，登记为技术债 `DEBT-10-01`（`§17.6`）。
不在本阶段统一到路由层的理由：改动 Phase 5 / 7 的**已验收**端点
会改变 FAILURE 审计的写入位置，需要重跑那两阶段的验收，而收益只是风格统一。

**但护栏已经装上**：`tests/test_route_authorization_guard.py`
让这个集合**不再扩大**（新增未声明端点即失败），并在修好时**不惩罚**。

---

## 7. BLOCKED CHECKS

**无。**

本阶段没有出现需要人类裁定的新设计决策：

- FINDING-10-01 的补交付属**补上已冻结的契约**，不是新增业务能力；
- 三个 INTERIM（10-01 / 10-02 / 10-03）都是 Spec 未枚举处的最小推导，
  改动面分别为"是否应用数据范围"、"两个权限位命名"、"两个动作的分类归属"，
  均不影响任何已冻结语义。

### 7.1 历史未冻结项在本次验收中的处置

| 项 | 状态 | 是否阻塞最终验收 |
|---|---|---|
| DD-01 MFA Provider | 未冻结；按 `00 §4` 明令禁止选产品级 Provider | 否（已按草案 A 落地并验收） |
| DD-02 Token 生命周期 | 未冻结；已按草案 A 落地并验收（004 PASS） | 否 |
| DD-03 Redis Key 命名 | 未冻结；限流键已登记（INTERIM-9-02），权限缓存尚未启用 | 否 |
| DD-08 日志分区 | DEFERRED；按 `06 §5` "后续"口径不分区 | 否 |
| DD-10 限流阈值 | 未冻结；全部做成配置项（INTERIM-9-01） | 否 |
| DD-12 错误码段位 | 未冻结；现用集中式 INTERIM 码 | 否 |
| DD-21 权限构建默认行为 | 未冻结；`build()` 默认行为**未改变** | 否 |
| CONFLICT-001 | **已关闭**（模型与契约已冻结并落地） | 否 |

所有历史阻塞项均已 CLOSED 或已降级为"不阻塞"的 INTERIM/DEFERRED。

---

## 8. 交付清单（本阶段新增）

| 文件 | 内容 |
|---|---|
| `app/repositories/log_query.py` | 审计日志检索 + 链路聚合 / 回放（读侧） |
| `app/services/log_query.py` | 归一化、参数兜底、成功审计 |
| `app/schemas/log_query.py` | 查询与响应 DTO（分页契约 `{list,total,pageNum,pageSize}`） |
| `app/api/v1/endpoints/audit_logs.py` | `08 §8` 的 4 条端点 |
| `tests/test_log_query_api.py` | 13 例（路由面 2 / 访问控制 3 / 审计 4 / 链路 3 + 1） |
| `tests/test_permission_matrix.py` | 11 例（权限矩阵五类主体） |
| `tests/test_route_authorization_guard.py` | 5 例（全路由授权护栏 + 自检） |
| `app/api/deps.py::API_PERMISSION_MARKER` | 依赖函数上的声明标记（供护栏扫描） |
| `docs/verification/010-final-acceptance-result.md` | 本文件 |
| `docs/DESIGN-DECISIONS.md §17` | INTERIM-10-01/02/03、FINDING-10-01/02、DEBT-10-01 |

---

## 9. 最终结论

```text
Build             4/4   PASS
Functional       12/12  PASS
Security          8/8   PASS
Permission Matrix 5/5   PASS
BLOCKED CHECKS    0
P0 / 高危未解决项 0
```

**PROJECT FINAL ACCEPTANCE: PASS**
