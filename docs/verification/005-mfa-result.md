# Verification 005 — MFA · 执行结果

| 项 | 值 |
|---|---|
| 验收依据 | `docs/verification/005-mfa.md`（裁判文件，**未修改**） |
| 执行 Phase | `PHASES.md` **Phase 5 — MFA**（= `docs/agent/PHASE-005-SESSION-MFA` 的 MFA 部分） |
| 执行时间 | 2026-09-25 00:35 UTC |
| 代码基线 | `f753e12`（feat: phase 5 mfa skeleton）+ 本次测试与收敛改动 |
| 前置判定 | Phase 5 执行**前**曾输出 `BLOCKED — NEED USER DECISION`（见 `docs/DESIGN-DECISIONS.md §11`）。人类随后下达"不要询问我，完成所有任务"，Agent 依据已写明的草案 A 继续落地，**只采用不与 Frozen Spec 冲突的选项**（见 `docs/DESIGN-DECISIONS.md §12`） |
| 数据库变化 | **有**。新增 `mfa_policies` / `user_mfa` / `mfa_challenges` 三表；迁移 `phase5_dd24`（Revises `phase4_dd02`）。`alembic check` → `No new upgrade operations detected.` |
| 执行方式 | `.\scripts\dev.ps1 -Action verify` 等价链路（ruff check + ruff format --check + mypy + pytest），另加 `alembic check` |
| 门禁结果 | ruff `All checks passed!` ｜ format `170 files already formatted` ｜ mypy `Success: no issues found in 83 source files` ｜ alembic `No new upgrade operations detected.` ｜ pytest **805 passed / 0 failed**（`EXIT=0`） |
| 结论 | **PASS**（13/13 检查通过；0 项 BLOCKED；0 项 NOT RUN） |

> 说明：本文件是**执行结果记录**，不是验收裁判。
> `docs/verification/005-mfa.md` 的 13 个检查项内容**一字未改**。
>
> Phase 编号说明：本项目提交信息与迁移 `revision` 使用 `docs/agent/PHASE-00N` 编号，
> 与 `PHASES.md` 编号**相差一位**。本次执行 `PHASES.md` Phase 5 — MFA，
> 其 Session 部分已于 `68fb4e0` 完成并通过 `004-session.md` 验收。

---

## 1. 逐项判定

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 1 | MFA Provider 使用可扩展接口 | 算法必须经抽象委托，替换实现**不改服务层**（`04 §6`） | `MfaProvider` 是 `Protocol`（`setup` / `verify` + 生命周期钩子 `enable` / `disable`），服务层只持有 `MfaProviderRegistry`。测试用两个**结构不同的** Provider 分别跑通完整生命周期，服务层代码零改动 | **PASS** | `app/services/mfa.py:84`（Protocol）、`:123`（Registry）；`app/services/mfa_management.py:196`（`_require_provider`）；`tests/test_mfa_management.py::TestProviderAbstraction::test_any_protocol_conforming_provider_is_accepted`、`::test_credential_is_scoped_by_provider_name` |
| 2 | 支持 DISABLED / SETUP / ENABLED 生命周期 | 三态可迁移且**可观测**（`04 §6`） | `MfaStatus` 三态 + `apply_status` 按语义补写时间戳：进 `SETUP` 写 `setup_at` 并清 `enabled_at`；进 `ENABLED` 写 `enabled_at`；进 `DISABLED` 清 `enabled_at` **与密文**。`enable` 必须先通过一次真实校验（否则"配网失败但状态已 ENABLED"会把用户锁在门外）；`disable` 同样要求动态码（否则"拿到会话即可关掉二次验证"会成为绕过 MFA 的最短路径） | **PASS** | `app/models/enums.py:190` 附近（`MfaStatus`）；`app/repositories/mfa.py:65`（`apply_status`）；`app/services/mfa_management.py:247`、`:277`、`:310`；`tests/test_mfa_management.py::TestLifecycle`（7 例） |
| 3 | Secret 加密保存 | 库内**不得**出现明文（`04 §6`） | AES-256-GCM，密文 `v1.<base64url(nonce‖ct‖tag)>`，AAD 绑定 `user_id:provider`。测试以**原始 SQL** 扫 `user_mfa`，确认明文 secret 不出现在任何列；并验证密文可被正确密钥还原（否则只是"存了个没用的串"） | **PASS** | `app/core/security/aead.py`；`app/services/mfa_management.py:433`（`_decrypt`，明文唯一出口）；`tests/test_mfa_crypto.py`（30 例）；`tests/test_mfa_management.py::TestSecretEncryption::test_raw_sql_finds_no_plaintext_secret_anywhere`、`::test_no_row_anywhere_holds_a_plaintext_looking_secret` |
| 4 | Secret 不进入日志 | 日志 / 审计 / 异常文案均不得含 Secret（`00 §8`、`06 §4`、`10 §4`） | 审计事件只写"发生了什么"（`{"provider": ..., "status": ...}`），**从不**写明文 secret、provisioning URI 或密文。脱敏清单 `NEVER_LOG_KEYS` 已含 `mfa_secret` / `totp_secret` / `otp_secret` / `mfa_encryption_key` / `secret`。AEAD 的失败文案不含密钥内容 | **PASS** | `app/services/mfa_management.py:263`、`:300`、`:335`（审计载荷）；`app/core/masking.py:23`；`app/core/security/aead.py:179`；`tests/test_mfa_management.py::TestSecretNeverLeavesAudit`（3 例）；`tests/test_mfa_crypto.py::TestBuildSecretBoxFailClosed::test_error_message_leaks_no_key_material` |
| 5 | 支持按角色配置 MFA | 角色维度的"是否要求"可持久化并生效（`04 §7`） | `mfa_policies`（`subject_type ∈ {USER, ROLE}`，唯一键 `(subject_type, subject_id)`）；`RepositoryRoleMfaPolicySource` 读当前用户的有效角色集合。多角色合并取 **OR**（任一要求 ⇒ 要求） | **PASS** | `app/models/mfa.py:118`（`MfaPolicy`）；`app/repositories/mfa.py:129`（`get_role_policy_required`）；`app/repositories/role.py::list_active_role_ids_for_user`；`tests/test_mfa_management.py::TestRolePolicy`（5 例） |
| 6 | 支持按用户配置 MFA | 用户维度的"是否要求"可持久化且可撤销（`04 §7`） | 同一张 `mfa_policies` 的 `USER` 主体；`set_policy` 反复写入**覆盖**（不堆积，避免"哪一行说了算"变成第二真相）；`delete_policy` 回到"完全未表态"并如实返回是否删掉了东西 | **PASS** | `app/repositories/mfa.py:151`、`:163`；`tests/test_mfa_management.py::TestUserPolicy`（4 例，含 `test_user_policy_row_is_unique_per_subject`） |
| 7 | 用户级策略优先于角色级策略 | 解析必须**逐层短路**（`04 §7`） | `MfaPolicyResolver`：用户级已表态即返回（`source=USER`）；`NULL`（未表态）**继续向下**，`False`（明确不要求）**终止**解析。`describe_status` 把生效层如实暴露为 `source`，使"这个要求是谁提的"可回答 | **PASS** | `app/services/mfa.py:222`（`MfaPolicyResolver.resolve`）；`app/services/mfa_management.py:159`（`build_policy_resolver`）；`tests/test_mfa_management.py::TestPolicyPriority::test_user_overrides_role`、`::TestUserPolicy::test_user_policy_can_be_removed`；Phase 4 的 `tests/test_mfa_policy.py::TestPolicyPriority::test_explicit_user_false_terminates_the_chain` |
| 8 | 角色级策略优先于系统默认 | 角色级过后才轮到 system（`04 §7`） | 角色级已表态即返回（`source=ROLE`）；只有 user / role 两层都未表态才用 `system_default`（`source=SYSTEM`），全部未表态时为 `NONE` | **PASS** | `app/services/mfa.py:254`；`tests/test_mfa_management.py::TestPolicyPriority::test_role_overrides_system`、`::test_system_is_used_only_when_both_layers_say_nothing`、`::test_status_endpoint_reports_the_effective_source` |
| 9 | 登录流程正确触发 MFA | 已绑定用户登录必须**停在二次验证之前**（`04 §1` 第 6 步 / DD-23 方案 A） | `AuthService.login` 在第 6 步（口令已验证之后、签发令牌之前）先跑 `check_login`，再按"是否已绑定"分流：已启用 → **不建 Session**，返回一次性 `mfa_token`（TTL 300s、库内只存 SHA-256、达次数上限或成功即核销）；未绑定但策略要求 → 放行并标记 `mfa_setup_required`（JUDGMENT-MFA-01，理由见 `DESIGN-DECISIONS §12.2`）。`POST /auth/mfa/verify` 核销后才建 Session 并签发令牌对 | **PASS** | `app/services/auth.py:248`、`:257`、`:273`、`:320`；`app/api/v1/endpoints/auth.py:110`（登录分支）、`:147`（`/mfa/verify`）；`tests/test_mfa_api.py::TestLoginFlow`（7 例，含 `test_login_with_mfa_returns_a_challenge_not_tokens`、`::test_challenge_creation_does_not_create_a_session`）、`::TestChallengeHardening`（2 例）；`tests/test_mfa_management.py::TestChallengeLifecycle`（12 例） |
| 10 | MFA enable / disable 有安全日志 | 两类动作各留一条成功事件（`04 §8`） | `MFA_ENABLE` / `MFA_DISABLE`，携带 `resource_type="MFA"` 与 `resource_id`；载荷含 `status` 与（禁用时）`secret_cleared=true`。经 `AuthAudit` 发出 —— 选它而非 `AuditGuard`，因为 MFA 存在"操作者尚未确定"的事件（登录途中的挑战失败），编造一个 `CurrentActor` 会写出"看起来是某用户做的"假记录 | **PASS** | `app/audit/events.py:103`；`app/services/mfa_management.py:300`、`:335`；`app/services/auth_audit.py`（模块 docstring 说明选型理由）；`tests/test_mfa_management.py::TestSecurityAudit::test_setup_enable_disable_produce_success_events` |
| 11 | MFA failure 有安全日志 | 失败必须留痕且**不得因提前 `raise` 而绕过**（`10 §8`） | 四类失败各自独立可检索：`WRONG_CODE_ON_ENABLE` / `WRONG_CODE_ON_DISABLE` / `WRONG_CODE_ON_LOGIN` / `SECRET_UNAVAILABLE`。审计先于 `raise` 写入，因此异常路径不会绕过留痕 | **PASS** | `app/services/mfa_management.py:286`、`:322`、`:397`、`:454`；`tests/test_mfa_management.py::TestSecurityAudit::test_enable_failure_is_logged_with_reason`、`::test_disable_failure_is_logged`、`::test_login_failure_is_logged_with_actor_from_challenge`、`::test_secret_decryption_failure_is_logged` |
| 12 | 恢复流程不会泄漏 Secret | Secret 只能从 `setup` 流出一次 | **取 (c) 读法**：本 Phase **不新增**恢复码 / 管理员重置 MFA（两者都要求新增表与端点，超出 `08 §3`，属新增业务能力）。因此本条证明的是**反向命题**：除 `POST /auth/mfa/setup` 外不存在任何 Secret 流出路径 —— 以两条自动化护栏钉住：① 全部响应 DTO 中只有 `MfaSetupResponse` 带 `secret` 字段；② AST 扫描全仓库，`MfaSetupResponse` 的**构造点恰好一处**且在 setup 端点内。另断言无 recovery / backup 端点与表 | **PASS**（读法已登记） | `app/schemas/mfa.py:42`（唯一带 secret 的 DTO）；`app/api/v1/endpoints/mfa.py:68`（唯一构造点）；`tests/test_mfa_management.py::TestNoSecretOnReadSurfaces`（6 例）；`tests/test_mfa_api.py::TestResponseContract::test_setup_is_the_only_response_exposing_the_secret` |
| 13 | 未冻结的 V1 Provider 不得被 Agent 擅自定义为业务事实 | 产品代码内**零**具体算法 | `app/` 内无 TOTP / WebAuthn / SMS 实现，亦无对应模块；进程级 Provider 登记处出厂为空（`has_active() == False`）；无 Provider 时**fail-closed** 抛 `ConfigurationError` 而不是内置一个或静默降级。测试含 **AST 级护栏**：扫描 `app/**/*.py` 的 import，禁止 `pyotp` / `onetimepass` / `fido2` / `webauthn` / `yubico_client` / `twilio` / `qrcode`；并禁止 `app/` 下出现以 `totp` / `hotp` / `webauthn` / `fido` / `sms` 命名的模块。测试专用 Provider 仅存在于 `tests/` | **PASS** | `app/services/mfa.py:178`（空默认登记处）；`app/services/mfa_management.py:196`；`tests/test_mfa_management.py::TestNoConcreteProviderInProduct`（4 例）；`tests/test_mfa_api.py::TestRouteSurface` |

---

## 2. 裁判之外、本阶段必须自证的安全前提

裁判 005 未逐条列出以下四项，但它们是上表判定能成立的**前提**，
缺了它们，"Secret 加密保存""登录流程正确触发 MFA"等结论无法被证明。

| 前提 | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|
| AAD 必须绑定身份（DD-22 P3） | 密文不得可跨行复用 | 加密时把 `user_id:provider` 编入 AAD。测试构造真实攻击路径：把 A 的密文整行复制到 B 名下、两行都置 `ENABLED`，然后**受害者本人**发起登录 —— 解密必须失败（`ConfigurationError`），**不得**出现"用 A 的 secret 正常验证 B 的登录" | **PASS** | `app/services/mfa_management.py:208`（`_aad`）；`tests/test_mfa_crypto.py::TestAadBinding`（3 例）；`tests/test_mfa_management.py::TestSecretEncryption::test_ciphertext_cannot_be_moved_to_another_user` |
| 挑战令牌不落明文 | 库内只有哈希（与 access / refresh 同口径） | `mfa_challenges.token_hash` 为 SHA-256；明文令牌只回给客户端一次。测试以原始 SQL 反查，确认库内不存在明文令牌值 | **PASS** | `app/repositories/mfa.py:185`（`create_challenge`）、`:203`（按哈希命中）；`tests/test_mfa_management.py::TestChallengeLifecycle::test_challenge_token_is_only_stored_as_hash` |
| MFA 失败不得锁定账号 | 防暴力由**挑战级作废**承担（DD-23 方案 A） | 连续失败达 `MAX_CHALLENGE_ATTEMPTS`（5）即作废**该挑战**，但 `failed_login_count` 与 `locked_until` **保持不变** —— `10 §5` 的锁定语义是"密码连续失败"，若把 MFA 失败也算进去，手机丢失的用户会被锁在账号外，而正确处置是走恢复流程 | **PASS** | `app/services/mfa_management.py:78`、`:379`；`tests/test_mfa_management.py::TestChallengeLifecycle::test_mfa_failure_does_not_lock_the_account`、`::test_challenge_is_burned_after_reaching_the_attempt_cap` |
| 生产环境密钥缺失必须启动失败 | `MFA_ENCRYPTION_KEY` 纳入 prod 校验 | 修复了 `DESIGN-DECISIONS §11.2` 记录的真实缺口：此前 `prod` 只校验 4 个密钥，唯独漏了 MFA 加密密钥 —— 意味着生产可以用空密钥启动，直到第一次有人绑定才报错 | **PASS** | `app/core/config.py:159`；`tests/test_config.py`（既有 prod 校验用例） |

---

## 3. BLOCKED CHECKS

**无。** 13 项检查全部 PASS，0 项 NOT RUN，0 项 BLOCKED。

本阶段**曾**触发 `BLOCKED — NEED USER DECISION`（编码前，见 `docs/DESIGN-DECISIONS.md §11`），
其后在人类"不要询问我，完成所有任务"的指令下按草案 A 继续执行。
执行过程**未**违反任何 Frozen 边界，具体取舍逐条登记在 `docs/DESIGN-DECISIONS.md §12`：

- **JUDGMENT-MFA-01**（§12.2）：策略要求但用户尚未绑定 → **放行登录**并标记 `mfa_setup_required`。
  阻断会**死锁**（绑定本身需要已认证会话），且存在替代路径的场景才允许阻断。
- **FINDING-MFA**（§12.3）：挑战签发不产生独立审计事件 —— `04 §8` 的安全日志清单只有
  setup / enable / disable / failure 四类，新增动作属**扩展 Spec**，故保持沉默。
- **INTERIM-5-07 / 5-08 / 5-09 / 5-10**（§12.4）：挑战 TTL、失败次数上限、
  多角色合并口径、`check_login` 占位分支退场。其中 **INTERIM-5-08 是对草案内部不一致
  的解释**（Q3"一次作废"与 Q4"5 次后作废"并存时 Q4 无意义），非新增要求。
- **裁判第 12 项的读法**：取 (c)（不新增恢复流程），已在
  `docs/DECISION-REQUEST-PHASE-5.md §5` 请求澄清，**尚未收到**；
  本 Phase 以自动化护栏把"Secret 只在 setup 流出一次"钉死，
  使该读法下的结论可证伪 —— 若人类裁定为 (a)/(b)，需**新增**表与端点，届时应重跑本验收。

---

## 4. 门禁与迁移证据

```text
--- ruff check ---            All checks passed!
--- ruff format --check ---   170 files already formatted
--- mypy ---                  Success: no issues found in 83 source files
--- alembic check ---         No new upgrade operations detected.
--- pytest ---                805 passed in 746.54s (0:12:26)
EXIT=0
```

**迁移**：`alembic/versions/20260924_2349_phase5_dd24_mfa_policies_credentials_and_challenges.py`

```text
phase4_dd02 -> phase5_dd24 (head)
```

三张新表（均为空表创建，无数据迁移）：

| 表 | 唯一约束 | 说明 |
|---|---|---|
| `mfa_policies` | `(subject_type, subject_id)` | `required` **可空**：`NULL` = 未表态，`False` = 明确不要求 |
| `user_mfa` | `(user_id, provider)` | `encrypted_secret` 为 `Text`（AEAD 密文长度可变；定长列会埋下**静默截断**风险） |
| `mfa_challenges` | `token_hash` | `attempts` / `consumed_at` 支撑限次与一次性核销 |

> 迁移在提交前**合并过一次**：曾生成第二条迁移只为修正 `mfa_challenges.created_at` 的列注释。
> 由于两条**均未提交**、且三张表当时为空表，故删除第二条并把修正并入首条，
> 使每个 Phase 概念对应一条迁移（降级链为 `phase4_dd02 → phase5_dd24`）。

**新增依赖**：`cryptography==46.0.3`（AEAD）。**未**引入任何 TOTP 类库 —— 引入即等于选定 Provider。

---

## 5. 测试覆盖对账

| 文件 | 层 | 例数 | 对应裁判条目 |
|---|---|---|---|
| `tests/test_mfa_crypto.py` | unit | 27 | 3、4 |
| `tests/test_mfa_policy.py` | unit | 13 | 7、8（Phase 4 既有；本次仅因占位分支退场而改写 1 例，总数不变） |
| `tests/test_mfa_management.py` | integration | 59 | 1、2、3、4、5、6、7、8、9、10、11、12、13 |
| `tests/test_mfa_api.py` | integration | 21 | 9、12、13 + 路由面 / 访问控制 |
| **合计** | | **120** | |

全量 pytest 由 Phase 4 收尾时的 697 增至 **805**（+108）。

---

## 6. 阶段边界与反向钉住

- **未预实现后续 Phase**：无字典 / 系统参数表（Phase 7）、无动态权限
  `GET /auth/permissions`（Phase 8）、无 rate limit / 幂等（Phase 9）。
- **未改动既有产出**：Phase 1~4 的模型、迁移、服务、端点均未修改，
  唯一的改动是 `app/services/mfa.py::check_login` 的**占位分支退场**
  （Phase 4 时"未实现"所以拒绝；现在实现已到位，改为返回要求），
  行为变更有专门用例钉住，且 fail-closed 分支一字未改。
- **`tests/test_session_api.py` 与 `tests/test_auth_api.py` 的反向护栏按计划换向**：
  曾断言"不存在任何 `mfa` 端点"（服务于 Phase 5 Session 阶段的"不得预实现"），
  现改为**正向**断言 `/auth/mfa*` 五条端点与 `08 §3` 逐条相等、且不得混入 `/admin` 域 ——
  防漂移能力保留，未删除护栏。
