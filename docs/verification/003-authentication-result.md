# Verification 003 — Authentication · 执行结果

| 项 | 值 |
|---|---|
| 验收依据 | `docs/verification/003-authentication.md`（裁判文件，**未修改**） |
| 执行 Phase | PHASE-004-AUTH（= `PHASES.md` Phase 3 — Authentication） |
| 执行时间 | 2026-09-24 14:05 UTC |
| 代码基线 | `2bacd00`（docs: phase 4 design decision request）+ Phase 4 工作区改动 |
| 前置裁定 | `docs/DECISION-REQUEST-PHASE-4.md` 四项草案**全部取方案 A**（人类批准，2026-09-24） |
| 执行方式 | `.\scripts\dev.ps1 -Action verify`（ruff check + ruff format --check + mypy + pytest） |
| 门禁结果 | ruff `All checks passed!` ｜ format `152 files already formatted` ｜ mypy `Success: no issues found in 74 source files` ｜ pytest **641 passed / 0 failed** |
| 结论 | **PASS**（22/22 检查通过；0 项 BLOCKED；1 项带 Phase 边界说明） |

> 说明：本文件是**执行结果记录**，不是验收裁判。
> `docs/verification/003-authentication.md` 的 22 个检查项内容**一字未改** ——
> 修改裁判文件以适配代码是明令禁止的行为。
>
> Phase 编号说明：本项目的提交信息与迁移 `revision` 使用 `docs/agent/PHASE-00N` 编号
> （`phase3_dd20` 对应 `PHASE-003-PERMISSION` = `PHASES.md` Phase 2），
> 与 `PHASES.md` 的编号**相差一位**。本次执行的是 `PHASE-004-AUTH`，
> 其裁判文件即 `003-authentication.md`（Auth 排在 Permission 之后）。

---

## 1. 逐项判定

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 1 | 登录流程按 Spec 执行 | `04 §1` 九步：lookup → status → lock → password verify → MFA → 口令到期 → create session → issue token → audit | `AuthService.login` 严格按该顺序执行，代码顺序与 Spec 步骤编号一一对应（含注释标注第几步） | **PASS** | `app/services/auth.py:120`（`login`）；`tests/test_auth_service.py::TestLoginSuccess`（6 例）；`tests/test_auth_api.py::TestLoginEndpoint::test_login_returns_envelope_and_token_pair` |
| 2 | 用户状态检查 | 非 ACTIVE 用户不得登录 | 第 2 步 `user.status is not UserStatus.ACTIVE` → 401；且**认证路径也复查**用户状态（禁用即时生效，不必等令牌过期） | **PASS** | `app/services/auth.py:153`；`app/services/session.py:230`；`tests/test_auth_service.py::TestLoginFailuresAreIndistinguishable::test_disabled_user_is_rejected_and_reason_recorded`、`tests/test_session_service.py::TestAuthenticate::test_user_disabled_after_login_is_rejected` |
| 3 | 锁定状态检查 | 锁定期内即使口令正确也必须拒绝 | 第 3 步先判 `locked_until > now` → 401；锁定期已过则**惰性解锁**（无需后台任务） | **PASS** | `app/services/auth.py:166`；`tests/test_auth_service.py::TestLockout::test_locked_account_rejects_correct_password_within_lockout`、`::test_lock_expires_after_thirty_minutes` |
| 4 | 密码校验 | 口令用 argon2id 校验，绝不比对明文 | 第 4 步 `get_password_hasher().verify(...)`；`admin_users.password_hash` 只存 argon2id 哈希 | **PASS** | `app/core/security/password.py`；`tests/test_auth_service.py::TestCredentialHygiene::test_plaintext_password_is_never_persisted`、`tests/test_password.py`（19 例） |
| 5 | MFA 检查 | 登录流程中存在 MFA 检查步骤，且按 `04 §7` 策略执行 | 第 6 步 `MfaService.check_login` 位于"口令已验证之后、签发令牌之前"；策略按 `user > role > system` 解析；策略要求但无 Provider → **fail-closed 明确失败**（`ConfigurationError`），不静默放行 | **PASS**（带 Phase 边界说明） | `app/services/mfa.py:292`（`check_login`）、`:252`（`MfaPolicyResolver.resolve`）；`tests/test_auth_service.py::TestMfaStep`（3 例）、`tests/test_mfa_policy.py`（13 例）。**边界**：具体 Provider（TOTP / WebAuthn / SMS）与 `/auth/mfa/*` 端点属 Phase 5 —— DD-01 方案 A 已裁定 003 的判定口径为"步骤存在且按策略执行" |
| 6 | 登录成功创建 Session | 登录成功后落库一条会话记录 | `sessions` 行包含 `user_id / login_at / last_active_at / ip / user_agent / device / expires_at / refresh_expires_at`，`revoked_at` 为 NULL | **PASS** | `app/services/session.py:132`（`create`）；`app/models/session.py:73`；`tests/test_auth_service.py::TestLoginSuccess::test_login_creates_session_and_returns_tokens`；`tests/test_session_service.py::TestCreateSession`（4 例） |
| 7 | 登录成功产生安全/审计记录 | 每次登录成功产生一条可检索的审计事件（`04 §8`） | `AUTH_LOGIN_SUCCESS`，`resource_type=SESSION`、`resource_id=` **本次会话 ID**、携带操作者 ID / 用户名 / IP / UA | **PASS** | `app/services/auth.py:229`；`app/audit/events.py`（`AUTH_LOGIN_SUCCESS`）；`tests/test_auth_service.py::TestLoginSuccess::test_successful_login_records_audit_with_session_id` |
| 8 | 连续 5 次失败后锁定 | 第 5 次连续失败即锁定，并单独记录锁定安全事件 | `failed_login_count` 累加至 `MAX_FAILED_LOGIN_ATTEMPTS`(=5) 时设 `locked_until`；同时写 `AUTH_LOCKOUT`（独立事件，不被失败噪声淹没） | **PASS** | `app/services/auth.py:248`（`_register_login_failure`）；`tests/test_auth_service.py::TestLockout::test_five_consecutive_failures_lock_the_account` |
| 9 | 锁定 30 分钟 | 锁定时长为 30 分钟，到期自动可登录 | `LOCKOUT_DURATION = timedelta(minutes=30)`；断言 `locked_until == now + LOCKOUT_DURATION`，且 `now+30min` 时可正常登录 | **PASS** | `app/core/security/password.py:35`（`LOCKOUT_MINUTES = 30`）；`tests/test_auth_service.py::TestLockout::test_five_consecutive_failures_lock_the_account`、`::test_lock_expires_after_thirty_minutes` |
| 10 | 密码至少 12 字符 | 11 位被拒、12 位通过 | `PASSWORD_MIN_LENGTH = 12`，边界两侧均有用例 | **PASS** | `app/core/security/password.py:30`；`tests/test_password.py::TestPasswordPolicy::test_exactly_min_length_boundary_passes`、`::test_one_below_min_length_is_rejected`；`tests/test_auth_service.py::TestChangeOwnPassword::test_weak_new_password_is_rejected` |
| 11 | 包含大写 | 缺大写被拒 | `_UPPERCASE` 规则，缺失即产生 `missing_uppercase` 违规 | **PASS** | `app/core/security/password.py:119`（`validate_password_policy`）；`tests/test_password.py::TestPasswordPolicy::test_missing_uppercase` |
| 12 | 包含小写 | 缺小写被拒 | `_LOWERCASE` 规则 | **PASS** | 同上；`tests/test_password.py::TestPasswordPolicy::test_missing_lowercase` |
| 13 | 包含数字 | 缺数字被拒 | `_DIGIT` 规则 | **PASS** | 同上；`tests/test_password.py::TestPasswordPolicy::test_missing_digit` |
| 14 | 包含特殊字符 | 缺特殊字符被拒 | 特殊字符规则 | **PASS** | 同上；`tests/test_password.py::TestPasswordPolicy::test_missing_special_character` |
| 15 | 最近 5 个密码不可重复 | 新口令命中当前口令或最近 5 条历史 → 拒绝 | `admin_user_password_histories` 留档；改密时先比对当前口令、再逐条比对最近 5 条历史；命中 → 400 + `violations` | **PASS** | `app/services/user.py:629`（`_prepare_password_change`）；`tests/test_auth_service.py::TestChangeOwnPassword::test_password_history_rejects_reuse`、`::test_new_password_equal_to_current_is_rejected` |
| 16 | 密码 90 天更换 | 超 90 天允许登录但**强制改密** | `is_password_expired` 判定；登录成功后置 `must_change_password = True` 并**落库**；`password_changed_at` 为空按 fail-closed 视为已过期 | **PASS** | `app/core/security/password.py:101`；`app/services/auth.py:219`；`tests/test_auth_service.py::TestLoginSuccess::test_login_succeeds_even_when_password_is_over_90_days_old`、`::test_unknown_password_change_time_forces_change`；`tests/test_auth_api.py::TestForcedPasswordChangeGate::test_login_after_90_days_reports_expired_password` |
| 17 | 管理员重置后首次登录强制改密 | 重置后首次登录必须改密，且服务端**强制**（不能靠客户端自觉）；同时必须存在解除路径 | `must_change_password=True` 时：`/auth/me`、`/auth/password`、`/auth/logout` 可访问（否则用户被困死），其余受保护端点由 `get_current_actor` 返回 **403**；`POST /auth/password` 是唯一解除路径，成功后置回 False | **PASS** | `app/api/deps.py:113`（`get_current_actor`）、`:126`（宽松入口）；`app/api/v1/endpoints/auth.py`；`tests/test_auth_api.py::TestForcedPasswordChangeGate`（7 例）；`tests/test_auth_service.py::TestChangeOwnPassword::test_successful_change_clears_must_change_flag` |
| 18 | 不记录密码 | 口令 / 口令哈希不得进入日志、审计、响应体 | 请求字段用 `SecretStr`（`repr` 为 `**********`）；审计只写原因码不写凭据；测试对成功 / 失败 / 锁定三条路径全量检查审计与响应文本 | **PASS** | `app/schemas/auth.py:47`；`app/core/masking.py`（`NEVER_LOG_KEYS`）；`tests/test_auth_service.py::TestCredentialHygiene::test_no_audit_event_contains_password_material`；`tests/test_auth_api.py::TestLoginEndpoint::test_password_is_never_echoed_back`、`::TestMeEndpoint::test_me_never_leaks_credentials` |
| 19 | Logout 正常失效 | 登出后令牌**立即**不可用；重复登出不报错 | 撤销 = 写 `revoked_at`，而每次请求都读该列 → 下一个请求必然 401（`10 §7`）；重复登出返回 200 + `already_revoked=true`（DD-11 方案 A 语义幂等） | **PASS** | `app/services/session.py:478`（`logout`）、`:183`（`revoked_at` 判定）；`tests/test_auth_api.py::TestLogoutEndpoint::test_logout_revokes_and_is_idempotent`；`tests/test_auth_service.py::TestLogoutAndMeDelegation::test_logout_revokes_issued_session` |
| 20 | Refresh Token 按安全规则保存 | 只存哈希、不存明文；轮换；复用即全族撤销 | 库中只有 SHA-256（唯一索引）；每次刷新轮换 access+refresh，旧 refresh 留档为 `ROTATED`；旧 refresh 再现 → 撤销**整个会话**（含新 access）+ `AUTH_TOKEN_REUSE_DETECTED`；7 天**固定不滑动** | **PASS** | `app/core/security/token.py:86`（`hash_token`）；`app/models/session.py:105`；`app/services/session.py:264`（`refresh`）、`:416`（`_revoke_for_reuse`）；`tests/test_session_service.py::TestPlaintextNeverPersisted`、`::TestRefresh`（8 例）；`tests/test_auth_api.py::TestRefreshEndpoint`（4 例） |

> 说明：裁判文件的 22 项中第 10~14 项（长度 / 大小写 / 数字 / 特殊字符）是 `00 §2` 的
> **口令复杂度策略**，其唯一实现点是 `app/core/security/password.py`（SSOT），
> Phase 2 已交付并由 `tests/test_password.py` 覆盖；本 Phase 的工作是让**登录与改密路径
> 真正调用它**，故证据同时引用既有策略用例与本次新增的"策略在改密路径上生效"用例。

---

## 2. BLOCKED CHECKS

**无。** 22 项检查全部 PASS，0 项 NOT RUN。

一项（#5 MFA 检查）带有 **Phase 边界说明**，性质是
"本 Phase 交付了步骤、策略解析与 fail-closed，具体算法 Provider 属 Phase 5"，
**不是** BLOCKED —— DD-01 方案 A 已明确裁定 003 的判定口径就是
"步骤存在且按策略执行"：

| CHECK | 边界 | 归属 |
|---|---|---|
| #5 MFA 检查 | 具体 Provider（TOTP / WebAuthn / SMS）、Secret 加密落库、`/auth/mfa/*` 端点、user/role 两级策略存储 | Phase 5（`005-mfa.md`） |

`/auth/mfa/*` 与 `/auth/permissions` **刻意未实现**，并由用例反向钉住，
防止"预实现后续 Phase"：

- `tests/test_auth_api.py::TestRouteSurface::test_auth_paths_exist_exactly_as_specified`
  → 断言 OpenAPI 路径中不存在任何 `/api/v1/auth/mfa*`，也不存在 `/auth/permissions`。

---

## 3. 本次执行中发现并修复的缺陷

### DEFECT-4-01（High）会话末尾 15 分钟内刷新必然 5xx（且时间语义自相矛盾）

- **现象**：`tests/test_session_service.py` 有 3 个用例因
  `CheckViolationError: ... violates check constraint "ck_sessions_refresh_expires_not_before_access"`
  失败。初看像"夹具数据不合法"，但把根因追到实现后发现不是。
- **根因**：`SessionService.refresh` 轮换时直接写
  `access_expires_at = now + ACCESS_TOKEN_TTL`（15 分钟），而**没有**考虑
  `refresh_expires_at`（会话总寿命上界，登录时刻 + 7 天固定不滑动）。
  于是一个**只有 5 分钟寿命**的会话在刷新后会得到一枚"名义上还能活 15 分钟"的
  access token —— `expires_at > refresh_expires_at`。后果有两层：
  1. **数据库层**：`sessions` 上的 `ck_sessions_refresh_expires_not_before_access`
     拒绝该 UPDATE → `IntegrityError` → 500。触发条件是"在会话最后 15 分钟内刷新"，
     即**每一个会话在其生命末尾都会踩到**，不是罕见边界。
  2. **语义层**：授权判定读的是 `expires_at`，所以这枚令牌"声称"的有效期
     比它所属的会话还长，把 DD-02 P2 冻结的"会话总寿命是硬上界"
     表达成了两句互相矛盾的话。
- **为什么夹具一开始像错的**：用例为构造"refresh 已过期但 access 未过期"而传了
  `access_ttl=8天 / refresh_ttl=7天` —— 这个状态在**正确实现**下是不可达的，
  夹具确实构造不出它。但正确的结论不是"改夹具了事"，而是
  "轮换路径漏了封顶"。
- **修复**：新增 `SessionService.rotated_access_expiry(now, *, refresh_expires_at)`
  = `min(now + ACCESS_TOKEN_TTL, refresh_expires_at)`，并附完整推演说明为何必须封顶；
  轮换路径统一走它。不变量因此**构造性成立**，CHECK 退化为纯粹的"TTL 用反"探针。
  客户端拿到的 `access_expires_at` 也从此与实际可用时间一致
  （原先会以为还有 15 分钟，实际 5 分钟后即被拒）。
- **防复发**：新增用例
  `tests/test_session_service.py::TestAuthenticate::test_session_total_lifetime_bounds_rotated_access_token`
  —— 构造"会话只剩 5 分钟"的会话，断言新 access 的到期时间被**封顶到会话结束**，
  且越过该时刻即被拒。该用例在修复前以 CHECK 违反告终。
- **未降低任何验收标准**：修复方向是**加强**（把上界从"靠 500 报错"变成"构造性保证"），
  没有放宽约束、没有删除安全判定、没有修改 Frozen Spec。
- **证据**：修复前 `tests/test_session_service.py` → `3 failed, 28 passed`；
  修复后 → **31 passed**。完整门禁由 641 passed 佐证。

---

## 4. 未修复但已登记的发现（不得静默处理）

| 编号 | 内容 | 影响 | 登记位置 |
|---|---|---|---|
| **FINDING-4-01** | `SessionService.authenticate` 中的 `is_refresh_expired` 判定在 DEFECT-4-01 修复后成为**冗余保险**（CHECK + 封顶共同保证 `expires_at <= refresh_expires_at`，故"refresh 过期"必然蕴含"access 过期"），因而不存在能触发该分支的合法数据状态，**该分支无法被测试覆盖** | 无（安全性由另外两处保证） | 本节 + 代码注释 `app/services/session.py:196`。**有意保留**：删掉它能让用例更好写，但代价是删掉一条安全性质；若将来 DD-02 改判为滑动续期，少写这一个 `or` 就会让"会话总寿命是硬上界"静默失效 |

### 与本次执行相关的 INTERIM 取值（已在 `docs/DESIGN-DECISIONS.md` 登记）

| 位置 | 取值 | 说明 |
|---|---|---|
| `app/core/config.py::auth_v1_prefix` | `/api/v1/auth` | 认证与 `/api/v1/admin` 分离（INTERIM-4-01） |
| `app/api/deps.py::_PASSWORD_CHANGE_REQUIRED_MESSAGE` | 强制改密期间返回 **403**（非 401） | 401 会让客户端误判"登录失效"并清掉会话，用户反而走不到改密那一步（INTERIM-4-02） |
| `app/api/v1/endpoints/auth.py` | `POST /auth/password` 为**补充端点** | `08 §3` 未列出，但 `04 §2` 的"必须改密"若无解除路径即为死锁（INTERIM-4-03） |
| `app/repositories/session.py::SESSION_ACTIVITY_WRITE_INTERVAL` | `last_active_at` 写抑制窗口 **60 秒** | 只影响时间戳新鲜度，不影响任何鉴权判定；否则每个受保护请求都会 UPDATE 一次 |
| `app/core/security/device.py::describe_device` | 设备粗分类为**启发式**，输出形如 `Chrome · Windows · desktop` | 明确**非安全依据**（仅展示与取证）；用于设备指纹将构成安全误判 |
| `app/services/auth.py`（模块 docstring） | 自动锁定时**不**把 `status` 改为 `LOCKED`；解锁时**不**清零 `failed_login_count` | 前者避免"到期后永久锁死"；后者保证"连续失败"语义（需登录成功才清零）。两项均已在此前报备 |

---

## 5. 结论

> **Verification 003: PASS**

- 22/22 检查通过，0 项 BLOCKED，0 项 NOT RUN。
- 门禁：ruff `All checks passed!` ｜ format `152 files already formatted` ｜
  mypy `Success: no issues found in 74 source files` ｜ pytest **641 passed / 0 failed**。
- Phase 4 新增测试 **148 例**
  （token 30 / device 11 / mfa_policy 13 / session_service 31 / auth_service 31 / auth_api 32）。
- 1 个缺陷（High）在本次执行中定位、修复并补上防复发测试；
  1 项发现（FINDING-4-01）**未被静默处理**，已连同保留理由显式登记。
- 未修改任何 Frozen Spec 或验收裁判文件；未引入未裁定的设计决策
  （DD-02 / DD-03 / DD-11 / DD-01 均按人类批准的方法 A 落地）。
