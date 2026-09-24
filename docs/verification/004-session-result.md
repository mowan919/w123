# Verification 004 — Session · 执行结果

| 项 | 值 |
|---|---|
| 验收依据 | `docs/verification/004-session.md`（裁判文件，**未修改**） |
| 执行 Phase | `PHASE-005-SESSION-MFA` 的 **Session 部分**（= `PHASES.md` Phase 4 — Session） |
| 执行时间 | 2026-09-24 15:10 UTC |
| 代码基线 | `2176cec`（feat: complete phase 4 authentication）+ Phase 5 工作区改动 |
| 前置裁定 | 无新增阻塞项。本阶段唯一的读法张力（SUPER_ADMIN 保护范围）按"取更严"收敛，见 §3 JUDGMENT-5-01 |
| 数据库变化 | **无**。`sessions` / `session_refresh_token_history` 为 Phase 4 交付；`alembic check` → `No new upgrade operations detected.` |
| 执行方式 | `.\scripts\dev.ps1 -Action verify`（ruff check + ruff format --check + mypy + pytest） |
| 门禁结果 | ruff `All checks passed!` ｜ format `159 files already formatted` ｜ mypy `Success: no issues found in 77 source files` ｜ pytest **697 passed / 0 failed**（`EXIT=0`） |
| 结论 | **PASS**（15/15 检查通过；0 项 BLOCKED；0 项 NOT RUN） |

> 说明：本文件是**执行结果记录**，不是验收裁判。
> `docs/verification/004-session.md` 的 15 个检查项内容**一字未改** ——
> 修改裁判文件以适配代码是明令禁止的行为。
>
> Phase 编号说明：本项目提交信息与迁移 `revision` 使用 `docs/agent/PHASE-00N` 编号，
> 与 `PHASES.md` 编号**相差一位**。本次执行 `PHASE-005-SESSION-MFA` 的 Session 部分，
> 对应 `PHASES.md` Phase 4 — Session，裁判文件为 `004-session.md`。
> 该文档的 **MFA 部分属 `PHASES.md` Phase 5**，本次**未实现**（见 §5 反向钉住）。

---

## 1. 逐项判定

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 1 | 可查询在线用户 | 存在一条可查出"当前哪些用户在线"的路径（`04 §5`） | `GET /api/v1/admin/sessions?online=true` 只返回在线会话，每行携带 `username` / `display_name` / `user_id` 与 `online` 布尔值。在线判定 = **未撤销 + 会话总寿命（refresh）未过 + 用户 ACTIVE 且未逻辑删除**（INTERIM-5-01） | **PASS** | `app/repositories/session.py:49`（`online_session_condition`）、`:328`（`_admin_conditions` 追加用户状态条件）；`app/services/session_management.py:120`（`is_session_online`）；`app/api/v1/endpoints/sessions.py:92`；`tests/test_session_management.py::TestOnlineStatus`（5 例）、`tests/test_session_api.py::TestResponseContract::test_online_filter` |
| 2 | 可查看 Session | 可列出会话并标识其归属（`04 §3` / `00 §5`） | `GET /sessions`（范围内全部会话）与 `GET /users/{id}/sessions`（指定用户）。响应含会话 ID、所属用户 ID / 用户名 / 显示名，以及 `04 §3` 要求的全部记录项 | **PASS** | `app/api/v1/endpoints/sessions.py:92`、`:140`；`app/schemas/session.py::SessionResponse`；`tests/test_session_management.py::TestSessionFields::test_row_exposes_every_required_field`；`tests/test_session_api.py::TestResponseContract::test_user_sessions_endpoint` |
| 3 | 可查看登录时间 | 响应可读出 `login_at` | `login_at` 由 `SessionService.create` 在登录时写入（与令牌签发同一时刻），响应字段 `login_at`（UTC） | **PASS** | `app/models/session.py:115`；`app/services/session.py:132`；`tests/test_session_management.py::TestSessionFields::test_row_exposes_every_required_field` |
| 4 | 可查看最后活跃时间 | 响应可读出 `last_active_at`，且认证热路径会更新它 | `last_active_at` 在每次成功认证时更新，带 **60 秒写抑制**（INTERIM 取值，避免高频请求把认证变成写热点）；响应字段 `last_active_at` | **PASS** | `app/repositories/session.py:52`（`touch`）、`:28`（`SESSION_ACTIVITY_WRITE_INTERVAL`）；`tests/test_session_service.py::TestAuthenticate::test_activity_write_is_suppressed_within_interval`；`tests/test_session_management.py::TestSessionFields::test_row_exposes_every_required_field` |
| 5 | 可查看 IP | 响应可读出 `ip` | 登录时记录 socket 对端地址（**不读** `X-Forwarded-For`，无可信代理列表时信任 XFF 等于允许伪造），响应字段 `ip` | **PASS** | `app/api/deps.py::client_ip`；`app/models/session.py:137`；`tests/test_session_management.py::TestSessionFields::test_row_exposes_every_required_field` |
| 6 | 可查看 User-Agent / Device | 响应可读出原始 UA 与设备粗分类 | `user_agent` 原样保存；`device` 为启发式分类（如 `Chrome · Windows · desktop`），代码中**显式标注为非安全信号** | **PASS** | `app/core/security/device.py::describe_device`；`app/models/session.py:142`、`:147`；`tests/test_device.py`（11 例）；`tests/test_session_management.py::TestSessionFields::test_row_exposes_every_required_field` |
| 7 | 可查看 expiry | 响应可读出到期时间 | 两个字段：`access_expires_at`（当前 access 的到期）与 `refresh_expires_at`（会话总寿命上界）。分开表达是**必须**的：access 15 分钟 / refresh 7 天，一个 `expires_at` 无法表达"access 已过期但 refresh 仍可换新" | **PASS** | `app/schemas/session.py::SessionResponse`；`app/models/session.py:127`、`:132`；`tests/test_session_management.py::TestSessionFields::test_row_exposes_every_required_field` |
| 8 | 可查看 revoked_at / reason | 已结束的会话可读出撤销时间与原因 | 响应字段 `revoked_at` / `revoke_reason`（枚举 `LOGOUT` / `ADMIN_REVOKE` / `REVOKE_ALL` / `TOKEN_REUSE_DETECTED`）；默认列表**包含**已撤销会话（排查"为什么掉线"必须能看到它） | **PASS** | `app/models/session.py:152`、`:157`；`tests/test_session_management.py::TestSessionFields::test_revoked_row_shows_time_and_reason`；`tests/test_session_api.py::TestResponseContract::test_user_sessions_endpoint` |
| 9 | 可 revoke 单个 Session | 撤销后该会话的令牌**立即**不可用（`10 §7`） | `POST /sessions/{id}/revoke` 置 `revoked_at` + `revoke_reason=ADMIN_REVOKE`，并把当时的 refresh 哈希留档为 `SESSION_REVOKED`。撤销后 access 与 refresh **两条路径**都被拒；重复提交返回成功（`already_revoked=true`，DD-11 方案 A 语义幂等） | **PASS** | `app/api/v1/endpoints/sessions.py:115`；`app/services/session_management.py:221`；`app/repositories/session.py:202`（`revoke_and_retire`）；`tests/test_session_management.py::TestRevokeOne`（4 例）、`::TestRevokeAll::test_revoke_all_retires_refresh_tokens_like_single_revoke`；`tests/test_session_api.py::TestRevokeOverHttp::test_revoke_invalidates_token_immediately`、`::test_revoke_is_idempotent` |
| 10 | 可 revoke 全部 Session | 该用户**全部**对应会话失效（`10 §7`） | `POST /users/{id}/sessions/revoke-all` 逐个终结**当前仍有效**的会话并返回 `revoked_count`。撤销后不存在任何可用会话；已到期 / 已撤销的会话**不被改写**（否则审计无法区分"到期"与"被踢"） | **PASS** | `app/api/v1/endpoints/sessions.py:163`；`app/services/session_management.py:259`；`app/repositories/session.py:409`（`list_active_for_user`）；`tests/test_session_management.py::TestRevokeAll`（6 例）；`tests/test_session_api.py::TestRevokeOverHttp::test_revoke_all_endpoint` |
| 11 | SUPER_ADMIN 可踢正常用户 | 超管对普通用户的会话撤销必须成功 | 超管走集中式 bypass（`10 §3`）：无需被授予 `SESSION_MANAGE`，且数据范围为全局 | **PASS** | `app/services/authorization.py:208`（`assert_can_manage_sessions`）、`:141`（`has_api_permission` 中的 bypass）；`tests/test_session_management.py::TestSuperAdminProtection::test_super_admin_can_revoke_normal_user`、`::TestApiPermission::test_super_admin_bypasses_api_permission` |
| 12 | Department Admin 只能踢管理范围内用户 | 范围内可踢；范围外必须被拒且留痕 | 范围条件下推到 SQL（`10 §10`），服务层再以 `ResolvedScope.allows_user` 显式判定：越范围 → **403 + FAILURE 审计**（不是"返回空"）。子部门包含在范围内（`00 §1#1`）；SELF 范围只能操作自己的会话 | **PASS** | `app/repositories/session.py:328`、`:356`；`app/services/session_management.py:343`（`_load_visible_user`）；`app/repositories/scope_filters.py::user_scope_condition`；`tests/test_session_management.py::TestDataScope`（8 例，含 `test_scope_is_applied_in_sql_not_in_memory`）；`tests/test_session_api.py::TestRevokeOverHttp::test_department_admin_kicks_only_in_scope`、`::TestAccessControl::test_out_of_scope_user_is_forbidden` |
| 13 | 任何管理员不能踢 SUPER_ADMIN | **任何**管理员（含另一位 SUPER_ADMIN）都不得经管理端点撤销超管会话 | `AuthorizationService.assert_can_revoke_session`：目标用户是 SUPER_ADMIN 即拒绝，**不区分操作者**。单踢与全踢两条路径都经过它。拒绝时**什么都不做**（会话保持原状）且写 FAILURE 审计 | **PASS**（读法取更严，见 JUDGMENT-5-01） | `app/services/authorization.py:164`；`app/services/session_management.py:221`、`:259`；`tests/test_session_management.py::TestSuperAdminProtection::test_even_super_admin_cannot_revoke_peer_super_admin`、`::test_global_admin_cannot_revoke_super_admin`、`::test_cannot_revoke_all_super_admin_sessions`；`tests/test_session_api.py::TestAccessControl::test_super_admin_cannot_be_kicked` |
| 14 | SUPER_ADMIN 只能本人 logout | 超管会话唯一合法的结束路径是本人 `POST /auth/logout` | 本人登出成功并把原因记为 `LOGOUT`；同一条会话经管理端点撤销则被拒（上条） | **PASS** | `app/services/session.py:478`（`logout`）；`tests/test_session_management.py::TestSuperAdminProtection::test_super_admin_session_ends_by_own_logout`；`tests/test_auth_api.py::TestLogoutEndpoint::test_logout_revokes_and_is_idempotent` |
| 15 | Refresh Token 不保存明文 | 库中只有哈希；任何响应 / 审计都不得出现明文 | `sessions.access_token_hash` / `refresh_token_hash` 与 `session_refresh_token_history.token_hash` 全部为 SHA-256（64 字符十六进制）。API 响应与审计事件中**既无明文也无哈希**（哈希不进入任何对外/审计输出） | **PASS** | `app/core/security/token.py::hash_token`；`app/models/session.py:105`、`:110`、`:239`；`tests/test_session_management.py::TestPlaintextNeverPersisted::test_raw_columns_hold_only_hashes`（以**原始 SQL** 反查库内实际值）、`::TestAuditAndMasking::test_no_token_material_in_audit`、`::TestSessionFields::test_response_model_exposes_no_token_material`；Phase 4 的 `tests/test_session_service.py::TestPlaintextNeverPersisted` |

---

## 2. 裁判之外、本阶段必须自证的安全前提

裁判 004 未逐条列出以下三项，但它们是上表判定能成立的**前提**，
因此一并执行并记录（缺了它们，"只能踢管理范围内用户"等结论无法被证明）。

| 前提 | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|
| 后端强制 API 授权（`08 §10`） | 每个受保护端点必须经过后端 API Permission 校验，不得只靠前端隐藏 | 四条端点统一经 `assert_can_manage_sessions`（`SESSION_MANAGE`），SUPER_ADMIN 走集中式 bypass；无权限 → 403 + FAILURE 审计 | **PASS** | `app/services/authorization.py:103`、`:208`；`tests/test_session_management.py::TestApiPermission`（3 例）；`tests/test_session_api.py::TestAccessControl::test_without_api_permission_is_forbidden` |
| 范围下推 SQL（`10 §10`） | 禁止"先查全部再在内存过滤" | `list_for_admin` / `count_for_admin` join `admin_users` 并在 SQL 施加 `user_scope_condition`；**计数与列表使用同一条件集**（`_admin_conditions` 单点构造），因此 `total` 也只覆盖范围内数据 | **PASS** | `app/repositories/session.py:328`、`:356`、`:389`；`tests/test_session_management.py::TestDataScope::test_scope_is_applied_in_sql_not_in_memory` |
| 强制改密期的访问控制（Phase 4 机制在本阶段生效） | 处于 `must_change_password` 的账号不得使用会话管理端点 | `CurrentActorDep`（严格入口）返回 **403**，不是 401 —— 否则客户端会误判"登录失效"而清掉会话 | **PASS** | `app/api/deps.py:113`；`tests/test_session_api.py::TestAccessControl::test_forced_password_change_blocks_session_endpoints` |
| 越权 / 安全拒绝必须留痕（`10 §8`） | 权限拒绝不得因提前 `raise` 而绕过审计 | 所有范围与授权判定包在 `AuditGuard.denial_audited` 内；越权用例均断言 `failures()` 非空 | **PASS** | `app/services/audit_guard.py`；`tests/test_session_management.py::TestSuperAdminProtection::test_even_super_admin_cannot_revoke_peer_super_admin`、`::TestDataScope::test_department_admin_cannot_revoke_out_of_scope_session`、`::TestApiPermission::test_missing_api_permission_is_denied` |

---

## 3. BLOCKED CHECKS

**无。** 15 项检查全部 PASS，0 项 NOT RUN，0 项 BLOCKED。

本阶段**没有**触发 `BLOCKED — NEED USER DECISION`：唯一的读法张力
（裁判"任何管理员" vs 冻结原文"其他管理员"）存在一个**同时满足两份文件且严格更强**的
收敛方案，因此不需要暂停 Phase，也不需要人类裁定即可执行。
该收敛仍在此显式登记，供人类复核。

### JUDGMENT-5-01 SUPER_ADMIN 会话保护取"任何管理员"读法

| 项 | 内容 |
|---|---|
| 张力 | `00 §1#7` / `04 §4`：**其他**管理员不能 revoke SUPER_ADMIN；裁判 `004 §13/§14`：**任何**管理员不能踢 SUPER_ADMIN，且只能本人 logout |
| 取法 | R1（更严）：目标为 SUPER_ADMIN 时，**任何**管理员都不得经管理端点撤销其会话（含另一位超管） |
| 为何不是"自行决定" | R1 蕴含 R0（"任何"⇒"其他"），同时满足两份文件；取 R0 会让裁判第 13 项 FAIL。按"不得弱化 / 不得把 FAIL 当 PASS"，只有 R1 可写 |
| 为何不是死洞 | 失陷的超管账号仍可被**禁用**（`authenticate` 每请求复查 `status`），且只有"最后一个超管"被禁止禁用 |
| 实现 | 新增 `assert_can_revoke_session`；**不修改** `assert_can_manage_user`（用户管理口径允许超管之间互相管理，复用它会让第 13 项 FAIL） |
| 已登记 | `docs/DESIGN-DECISIONS.md §9` |

### 本阶段登记但**不代为决定**的四项（FINDING，均不影响 PASS）

| 编号 | 内容 | 为何不自行处理 |
|---|---|---|
| FINDING-5-01 | `00 §5` 提到"Session 列表/**详情**"，而 `08 §5` 未列出 `GET /sessions/{id}`。本次以列表行的**完整字段**承载"详情"，未新增路由 | 在 `08 §5` 之外新增路由属扩展接口面；裁判也未要求独立详情页。需产品裁定 |
| FINDING-5-02 | 目标用户范围判定有两处口径：`UserService._load_target`（Phase 1/2 已验收）与 `ResolvedScope.allows_user`（文档化唯一入口），差异仅在 `include_self` 情形。本次统一用 `allows_user` | 统一到哪一份属已验收行为的改动，应由人类裁定后一次性完成（改 Phase 1/2 代码超出本阶段授权） |
| FINDING-5-03 | SUPER_ADMIN 保护只作用于 **revoke（写）**；**只读**查看仍由数据范围决定，不额外隐藏超管会话 | 在读侧排除超管需要一条**未文档化**的 SQL 规则，且会让扁平列表与定向查看两条路径不一致。更严的替代方案属新增业务规则 |
| FINDING-5-04 | 全踢的审计 `resource_id = None`（一次操作影响多条会话），目标用户与数量记在 `after_data` | 若需要"按目标用户检索被踢记录"，需 Phase 6 的审计查询支持 `after_data` 检索（审计落库 / DD-08 未冻结） |

---

## 4. 门禁与执行证据

```text
.\scripts\dev.ps1 -Action verify
--- ruff check ---
All checks passed!
--- ruff format --check ---
159 files already formatted
--- mypy ---
Success: no issues found in 77 source files
--- pytest ---
697 passed in 608.32s (0:10:08)
EXIT=0
```

- 通过数从 Phase 4 的 **641** 增至 **697**（本阶段新增 **56** 例：
  `tests/test_session_management.py` 40 例 + `tests/test_session_api.py` 16 例），
  且**无任何既有用例被删除或跳过**（`--strict-markers` 生效，无 xfail/skip 新增）。
- `alembic check` → `No new upgrade operations detected.`（本阶段无模型 / 迁移改动）。
- Phase 4 的会话生命周期用例（`tests/test_session_service.py` 31 例、
  `tests/test_auth_service.py` 31 例、`tests/test_auth_api.py` 32 例）
  在本次重构 `SessionService.revoke`（改为委托 `revoke_and_retire`）之后**全部仍然通过** ——
  证明该重构是纯提取，未改变既有语义。

### 新增 / 修改的交付物

| 类型 | 文件 |
|---|---|
| 新增（模型无关） | `app/schemas/session.py`、`app/services/session_management.py`、`app/api/v1/endpoints/sessions.py` |
| 修改 | `app/repositories/session.py`（管理侧查询 + `revoke_and_retire` + `online_session_condition`）、`app/services/authorization.py`（`SESSION_MANAGE` + `assert_can_revoke_session`）、`app/services/session.py`（`revoke` 委托统一实现）、`app/api/deps.py`、`app/api/v1/router.py`、`app/audit/events.py`（`SESSION_READ`） |
| 测试 | `tests/test_session_management.py`（40 例）、`tests/test_session_api.py`（16 例） |
| 文档 | `docs/DESIGN-DECISIONS.md §9/§10`、本文件、`docs/verification/VERIFICATION_INDEX.md` |
| **数据库** | **无变化**（`alembic check` → `No new upgrade operations detected.`） |

### 路由面（实测 OpenAPI）

```text
/api/v1/admin/sessions                              ['GET']
/api/v1/admin/sessions/{session_id}/revoke          ['POST']
/api/v1/admin/users/{user_id}/sessions              ['GET']
/api/v1/admin/users/{user_id}/sessions/revoke-all   ['POST']
```

---

## 5. 与裁判文件 / 后续 Phase 的边界

- `docs/verification/004-session.md` **一字未改**；本文件只是执行结果记录。
- 本阶段执行的是 `PHASE-005-SESSION-MFA` 的 **Session 部分**；
  该文档的 **MFA 部分**（Provider 实现、`/auth/mfa/*`、Secret 加密落库、
  user/role 两级策略存储）属 `PHASES.md` Phase 5，**未预实现**。
- 由用例反向钉住，防止"预实现"与接口面漂移：

| 断言 | 用例 |
|---|---|
| 会话端点**恰好**只有 `08 §4` / `08 §5` 列出的四条（无 `GET /sessions/{id}`、无 `/sessions/online`） | `tests/test_session_api.py::TestRouteSurface::test_session_paths_exist_exactly_as_specified` |
| 用户 CRUD 端点（`08 §4` 其余部分）不得提前挂载 | 同上 |
| 任何 `mfa` 端点仍不存在 | `tests/test_session_api.py::TestRouteSurface::test_mfa_endpoints_still_absent` |

- 与 Phase 4 的一致性：会话终结（置撤销 + 留档 refresh 哈希）只有
  `SessionRepository.revoke_and_retire` 一处实现，本人登出 / 单踢 / 全踢共用 ——
  因此 `10 §7` 在三条路径上的效果逐字段一致，不会出现
  "登出退役了哈希、踢下线没有"的取证差异。

---

## 6. 仍需人类处置的历史缺口（非本阶段引入）

| 缺口 | 状态 | 要求 |
|---|---|---|
| `docs/verification/001-organization-user.md`（13 项）从未产出结果文件 | 已在 `VERIFICATION_INDEX.md` 记为 **NOT RUN** | **Phase 10 之前必须补做**，不得因"代码已写"记 PASS |
