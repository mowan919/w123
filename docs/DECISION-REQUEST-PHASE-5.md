# BLOCKED — NEED USER DECISION（Phase 5 / MFA）

> 本文件**不是 Spec**，也不修改任何冻结结论。
> 它是 Agent 在 `PHASES.md` Phase 5（MFA）遇到的**设计阻塞点**的正式决策请求，
> 依据 `AGENTS.md §4`（"先停止扩展、记录问题、说明原因、不得自行扩大范围"）、
> `AGENTS.md §12`（"Verification 清单全部通过**或明确记录 Blocked 项**"）、
> `AGENTS.md §14`（禁止"以'未来再做'为由跳过当前 Spec 必须项"）
> 以及用户执行协议第七节（"真正的设计决策必须暂停"）输出。
>
> 依据用户既有裁定"**由我起草，你审批**"，本文档包含 Agent 起草的**契约草案**。
> 审批通过后，Agent 将按草案实现，并回填 `docs/DESIGN-DECISIONS.md`。
>
> **前置状态**：Phase 4（Session）已完成，`Verification 004` **PASS（15/15，0 BLOCKED）**，
> 提交 `68fb4e0`，已推送 `origin/main`。
> **本 Phase 未写入任何 MFA 业务代码**（`git status` 干净）。

---

## 0. 阻塞总览

| 编号 | 主题 | 阻塞严重度 | 影响的验收项（`005-mfa.md`） |
|---|---|---|---|
| **DD-01** | V1 具体 MFA Provider（算法选型） | **PHASE-5-BLOCKER** | 第 1、2、3、9、10、11、13 项 |
| **DD-22** | MFA Secret 加密方案（算法 + 密文格式 + 密钥来源） | **PHASE-5-BLOCKER** | 第 3、12 项 |
| **DD-23** | MFA 挑战 / 会话续接机制（登录如何切到 `/auth/mfa/verify`） | **PHASE-5-BLOCKER** | 第 1、9、11 项 |
| **DD-24** | MFA 策略（user / role）与凭据（`user_mfa`）的存储模型 | **PHASE-5-BLOCKER** | 第 2、5、6、7、8、10 项 |
| **—** | 裁判第 12 项"恢复流程不会泄漏 Secret"**无 Spec 依据** | **NEEDS CLARIFICATION** | 第 12 项 |

**已冻结、无需裁定且 Agent 可直接实现的部分**（不构成阻塞）：

- `MfaProvider` 抽象接口的存在与形态（`04 §6` 的 `setup / verify / enable / disable`）——
  **Phase 4 已交付**（`app/services/mfa.py::MfaProvider`，Protocol）；
- 生命周期**取值** `DISABLED / SETUP / ENABLED`（`04 §6`）——
  **Phase 4 已交付**（`app/models/enums.py::MfaStatus`）；
- 策略**层级与优先级** `user > role > system`（`04 §7` / `00 §1#10` / `15 D-010`）——
  **Phase 4 已交付**（`app/services/mfa.py::MfaPolicyResolver`）；
- "Secret 必须加密保存"**这条义务本身**（`04 §6`）与"MFA Secret 绝不记录"
  （`00 §1#12` / `06 §4` / `10 §4` / `13 §2`）；
- 安全日志事件类别 `MFA setup / enable / disable / failure`（`04 §8`）——
  **Phase 4 已登记枚举**（`app/audit/events.py::AuditAction.MFA_*`）；
- MFA 端点的**路径清单**（`08 §3`：`GET /auth/mfa`、
  `POST /auth/mfa/setup` / `enable` / `disable` / `verify`）；
- "未冻结的 V1 Provider 不得由 Agent 宣布为需求事实"
  （`00 §4` / `16 §待冻结项#1` / `PHASES.md Phase 5`）；
- 脱敏基建（`app/core/masking.py::NEVER_LOG_KEYS` 已含 `mfa_secret` /
  `totp_secret` / `otp_secret` / `mfa_encryption_key`）。

> **即：阻塞全部来自"选哪个算法 / 密钥怎么加解密 / 二次验证怎么续接 / 两级策略存哪里"
> 这四类技术设计决策。业务规则（策略层级、事件类别、端点路径）已冻结，且多数已在 Phase 4 落地。**

---

## 1. 问题

`PHASES.md` Phase 5 的目标是"**实现可扩展 MFA Provider 架构**"，
并明确"V1 Provider 未冻结时，不得自行宣布具体 Provider 为需求事实"。
裁判文件 `docs/verification/005-mfa.md` 共 13 项。

Spec 冻结了**抽象的形状**（`04 §6`）、**策略的层级**（`04 §7`）、
**事件类别**（`04 §8`）与**端点路径**（`08 §3`），
但没有冻结**任何一个具体 Provider**，并且 `07 §7` 明确写道：

```text
具体字段随 Provider 设计确定。
```

这一句话把"**持久化模型**"直接绑定到"**尚未冻结的 Provider 选型**"上。
因此 Phase 5 的阻塞不是"某个参数没定"，而是：

1. **没有算法** → 无法确定 `secret` 的形态（TOTP 的可重算共享密钥 / WebAuthn 的公钥 /
   Email·SMS 的通道凭据），也就无法确定"加密保存"的义务形态与密文列；
2. **没有加密方案** → 无法写 `encrypted_secret` 列，也无法回答"密钥缺失时怎么办"；
3. **没有挑战机制** → `08 §3` 列了 `POST /auth/mfa/verify`，
   但 `04 §1` 的顺序图把 `create session` 放在 `MFA check` **之后**，
   这意味着"密码已通过但 MFA 未完成"的中间态必须有一个**载体**，
   而这个载体的形态完全没有 Spec 依据；
4. **没有策略存储模型** → `04 §7` 要求"按用户 / 按角色"，
   但 `07 §7` 给出的 `user_mfa` 字段全是**凭据**字段，没有一处表达"是否要求"。

上述四项**互相耦合**（密文格式决定列类型、Provider 选型决定 secret 形态、
挑战机制决定登录响应契约、策略模型决定迁移脚本），
因此不存在"先做一半、其余等裁定"的安全切分 —— 强行切分会产生**确定性返工**。

---

## 2. 当前 Spec 原文（逐条引用）

`docs/spec/04-认证MFA与Session.md`

```text
§1 Login 流程：username/password → user lookup → status check → lock check
              → password verify → MFA check → create session → issue token
              → audit/security log → response
              （注意：create session 在 MFA check **之后**）
§6 MFA：Provider 必须抽象，例如：
            class MfaProvider:
                setup() / verify() / enable() / disable()
        生命周期：DISABLED → SETUP → ENABLED
        Secret 必须加密保存。
§7 MFA Policy：支持 system default / role policy / user policy；
        优先级 user > role > system。
        V1 具体 Provider 尚未冻结。
§8 安全日志：记录 … MFA setup/enable/disable/failure …
```

`docs/spec/00-需求冻结确认表.md`

```text
§1 冻结表 #10：MFA —— 按角色 + 按用户；用户级优先；V1 Provider 尚未冻结
§1 冻结表 #12：日志脱敏 —— phone/email/token/password/MFA Secret 按规则处理
§4 MFA：支持扩展 Provider 架构，例如 TOTP、Email、SMS、WebAuthn/Passkey 等，
        但 V1 的具体 Provider 尚未冻结，不得由 Agent 擅自确定为最终需求。
        MFA 策略优先级：User Policy > Role Policy > System Default
```

`docs/spec/07-数据库设计.md §7`

```text
建议包含：user_mfa / provider / status / encrypted_secret /
          setup_at / enabled_at / verified_at
具体字段随 Provider 设计确定。
```

`docs/spec/15-需求决策记录.md`

```text
D-010 MFA —— 决定：按角色 + 按用户。优先级 user > role > system。
              V1 具体 Provider 尚未决定。
D-012 脱敏 —— … MFA Secret never
```

`docs/spec/16-完整性检查.md`

```text
## 技术设计待冻结项
以下项目在业务 Spec 中不能被 Agent 擅自当作最终产品决策：
1. V1 具体 MFA Provider
…
这些属于技术设计决策，应在实现相应 Phase 前冻结。
```

`docs/spec/05-字典与系统参数.md`

```text
系统参数候选 … login max attempts / password minimum length / MFA default policy
参数必须有类型、默认值、状态、描述和审计。
```

`docs/spec/10-安全设计.md`

```text
§4 不得记录：password / password hash 到普通业务日志 / MFA secret /
            refresh token plaintext / access token plaintext
§6 MFA：Secret 加密存储。
        MFA verify 应有 rate limit / anti-brute-force。
```

`docs/spec/13-运维部署.md`

```text
§2 敏感配置：signing secret / encryption key / MFA encryption key
   应通过环境变量或正式 Secret Management 注入。
§5 监控：… MFA failure …
```

`docs/spec/11-缓存并发幂等.md`

```text
§1 Redis 用于 … rate limit … 具体 Key 命名规范在技术实现阶段冻结。
```

`docs/agent/PHASES.md`

```text
## Phase 5 — MFA
实现可扩展 MFA Provider 架构。
注意：V1 Provider 未冻结时，不得自行宣布具体 Provider 为需求事实。
验收：docs/verification/005-mfa.md
```

`docs/agent/PHASE-005-SESSION-MFA.md`

```text
V1 MFA Provider 未冻结。
不得自行把某个具体 Provider 宣布为最终业务需求。
```

**Spec 全文没有规定**：具体 Provider 是哪一个（TOTP / Email / SMS / WebAuthn 仅作为
"例如"被列出）；Secret 的加密算法与密文格式；密钥来源之外的密钥管理方式；
"MFA 要求"这一策略的**存储位置**；"密码通过但 MFA 未完成"的**中间态载体**；
挑战令牌的形态与 TTL；MFA 失败是否计入账号锁定；`user_mfa` 与策略是
同表还是分表；system 级默认值放环境变量还是系统参数表；
以及裁判书里出现的"**恢复流程**"究竟指什么。

---

## 3. 代码现状

| 能力 | 状态 |
|---|---|
| MFA 策略优先级解析 `user > role > system` | ✅ 已有：`app/services/mfa.py::MfaPolicyResolver`（含 `MfaPolicySource` 枚举） |
| "未表态"与"明确不要求"的区分 | ✅ 已有：`UnsetUserMfaPolicySource` / `UnsetRoleMfaPolicySource` 返回 `None` |
| `MfaProvider` 抽象 | ✅ 已有：`MfaProvider` Protocol（`setup / verify / enable / disable`）+ `MfaSetupMaterial` |
| Provider 登记处 | ✅ 已有：`MfaProviderRegistry`（**Phase 4 刻意注册为空**，`has_active()` 恒为 False） |
| 生命周期枚举 | ✅ 已有：`app/models/enums.py::MfaStatus`（DISABLED / SETUP / ENABLED） |
| 登录流程 MFA 步骤 | ✅ 已有：`MfaService.check_login`，**fail-closed**（策略要求但无 Provider → `ConfigurationError`） |
| system 级默认值 | ✅ 已有：`settings.mfa_required_default`（**默认 False**） |
| 安全日志事件枚举 | ✅ 已有：`AuditAction.MFA_SETUP / MFA_ENABLE / MFA_DISABLE / MFA_FAILURE`（**仅登记，无产生点**） |
| 脱敏规则 | ✅ 已有：`NEVER_LOG_KEYS` 含 `mfa_secret` / `totp_secret` / `otp_secret` / `mfa_encryption_key` |
| `MFA_ENCRYPTION_KEY` 配置项 | ⚠️ **声明存在但无消费者**（`app/core/config.py`）；且 `APP_ENV=prod` 的密钥校验**未包含该键** |
| 加密 / 解密设施 | ❌ **完全不存在**：`app/core/security/` 仅有 `device.py` / `password.py` / `token.py` |
| `user_mfa` 表 / 策略表 / 挑战表 | ❌ 未创建（`app/models/` 无任何 MFA 模型） |
| `/auth/mfa*` 端点 | ❌ 未实现（`app/api/v1/endpoints/auth.py` docstring 明确标注"→ Phase 5"） |
| MFA 相关测试 | ✅ 已有：`tests/test_mfa_policy.py`、`tests/test_auth_service.py::TestMfaStep`（覆盖策略解析与 fail-closed） |

---

## 4. 为什么阻塞（不能自行决定的具体理由）

1. **`07 §7` 把持久化绑在未冻结的选型上**：
   "具体字段随 Provider 设计确定"是 Spec **显式留下的待决项**，
   而 `16 §待冻结项#1` 又规定这类事项"应在实现相应 Phase 前冻结"。
   现在正是"实现相应 Phase"，因此必须先冻结。
2. **`secret` 的形态随算法而变，"加密保存"的义务也随之而变**：
   TOTP 的 secret 是可重算动态码的**共享密钥**，必须**可解密**；
   WebAuthn 存的是**公钥**，本就不需保密（只需防篡改）。
   在不选定算法的前提下写死"AEAD 加密 + 可解密"，等于**替 Provider 选型做了决定**。
3. **撤销语义与挑战中间态存在结构性张力**：
   Phase 4 已冻结"不透明 Token + PG 唯一真源 + 每请求回查 `revoked_at`"。
   `10 §7` 要求"Revoke 后 Token 必须不能继续访问"。
   若为了让 `/auth/mfa/verify` 能识别用户而**提前建 Session**，
   那么"只输对密码、未过 MFA"的人会立刻出现在 Phase 4 已验收的**在线用户**列表里
   （在线判定 = 未撤销 + 未过期 + 用户 ACTIVE），
   这既是业务错误，也把"认证是否完成"变成了一个**可选列**——
   漏检一处即为认证绕过。这个取舍决定认证子系统的形态，必须由人类裁定。
4. **策略的存储位置是库表决策，不是实现细节**：
   `04 §7` 要求按用户 / 按角色，`07 §7` 的字段清单里**没有**任何"是否要求"的列。
   因此必须新增存储。而"策略与凭据同表还是分表""role 级策略是否复用
   `roles` 表加列""`NULL` 是否表示未表态"都会**写进 Alembic 迁移**——
   库表一旦落库，回退成本高，属 `AGENTS.md §9` 的数据库变更范畴。
5. **`05 §5` 与现状存在跨 Phase 张力**：
   `05 §5` 把 "MFA default policy" 列为**系统参数**（"参数必须有类型、默认值、
   状态、描述和审计"），而系统参数属 **Phase 7**；
   现状是环境变量 `mfa_required_default`（需重启才生效、无审计）。
   是"Phase 5 继续用环境变量 + Phase 7 迁移"，还是"Phase 5 就地建参数表"
   （会与 Phase 7 交付重叠、可能造成两套参数机制），
   属于**跨 Phase 边界**问题，Agent 不得单方面扩大或缩小 Phase 5 范围。
6. **裁判第 12 项没有任何 Spec 依据**：
   在 `docs/` 全域检索 `恢复流程` / `恢复码` / `备用码` / `recovery code` /
   `backup code`，**唯一命中就是裁判书自己那一行**；
   `docs/spec/` 全域检索 `恢复` / `recovery` 结果为**空**。
   该项要求的"恢复流程"既无功能定义、也无端点、也无数据模型。
   按 `AGENTS.md §4`，Agent 必须"先停止扩展、记录问题"，而不是自行发明一套恢复机制。
7. **需求密度与裁剪风险**：`02 §1` / `03 §2` / `06 §4` 等多处对 MFA 的描述
   只是"提及"（例如 `09` 第 8 行"MFA 有必要的 rate limit"、
   `06` 第 43 行"MFA Secret → never log"），
   它们**依赖 Phase 5 先存在**。若 Agent 自行压低 Phase 5 的交付面，
   这些后续 Phase 的验收会连带失去依据。

---

## 5. 草案

### 5.1 DD-01 —— V1 具体 MFA Provider

#### 方案 A（**推荐**，最贴合 `PHASES.md` 字面要求）：不选定产品级 Provider

- `app/` 内**零算法实现**（不出现 TOTP / WebAuthn / Email / SMS 任何一者）；
- 交付"Provider-无关"的完整骨架：策略持久化、凭据表、加密、生命周期迁移、
  挑战机制、`/auth/mfa*` 端点、审计——**全部按抽象接口工作**；
- 在 `tests/` 内提供一个**测试专用 Provider**（仅存在于测试代码，**不进入 `app/`**，
  **不默认激活**），用于让裁判第 1 / 2 / 9 / 10 / 11 项获得**可端到端执行的证据**；
- 效果：裁判第 13 项可判 **PASS**（有证据证明 `app/` 内无具体 Provider、
  且未把任何 Provider 宣布为需求事实）；第 1 项的"可扩展"由测试 Provider
  证明"注册即插即用"。

| 项 | 结果 |
|---|---|
| 满足 `00 §4` / `16 #1` / `PHASES.md` | ✅ 完全满足 |
| 满足裁判第 1 / 2 / 9 / 10 / 11 项 | ✅ 可验证（机制正确、算法可插拔） |
| **残留缺口** | ⚠️ **生产环境仍无可用二次验证**：`MFA_REQUIRED_DEFAULT=true` 时登录 fail-closed（Phase 4 行为不变）。即"Phase 5 交付后系统仍不具备生产可用的 MFA" |

**这个残留缺口必须由人类显式接受**——否则就是"以完成验收为名交付了不可用的能力"。

#### 方案 B（**推荐备选**，产品完整）：冻结 **TOTP** 为 V1 Provider

- 理由：`04 §6` 的四个动作与 `MfaSetupMaterial.provisioning_uri` 字段，
  其典型用途正是 TOTP 的 `otpauth://` 配网 URI；
  且 TOTP **无需任何外部通道**（不要 SMTP、不要短信网关、
  不要 WebAuthn 要求的域名 / 浏览器 / 安全密钥前提），
  是当前项目唯一"零新增基础设施"即可投产的选项。
- 需要**一并冻结**的参数：

| # | 参数 | 草案取值 | 说明 |
|---|---|---|---|
| T1 | 摘要算法 | SHA-1 | RFC 6238 默认；`otpauth://` 生态兼容性最好 |
| T2 | 动态码位数 | 6 | 主流客户端默认 |
| T3 | 时间步长 | 30 秒 | 主流客户端默认 |
| T4 | 容错窗口 | ±1 步（±30 秒） | 不设窗口会让慢时钟用户频繁失败；放宽到 ±2 步显著扩大暴力面 |
| T5 | 是否允许码重用 | **不允许**：同一个时间步内已成功用过的码不得再次使用 | 否则 T 步内可重放。实现方式需裁定（记最后成功步长，或落库去重） |
| T6 | 是否新增第三方依赖 | 见 `§8` 第 2 问 | 自行实现 TOTP 约 40 行，但需自担正确性风险 |

- 代价：`secret` 形态确定为 **base32 共享密钥**（可解密，故 `DD-22` 的 AEAD 方案成立）；
  并需要正式冻结上表参数。

#### 方案 C：冻结 **Email / SMS** 之一为 V1 Provider

- 需要**外部投递通道**（SMTP 或短信网关），而 Secret 管理选型（`16 §9` DD-09）
  尚未冻结；当前项目**不存在**任何邮件 / 短信基础设施。
- 引入新的失败模式：投递失败 → 用户无法登录（且是"密码对、也拿不到码"的死路）。
- 结论：**不推荐**在 V1 引入。

#### 方案 D：MFA 整体延后，Phase 5 判 BLOCKED

- `AGENTS.md §14` 禁止"以'未来再做'为由跳过当前 Spec 必须项"，
  因此这只能是**人类明确裁定延后**的结果，不能由 Agent 自行选择；
- 连带影响：`006` 第 43 行"MFA Secret → never log"、`009` 第 8 行"MFA 有必要的 rate limit"、
  `010` 第 18 / 33 行的 MFA 项都将缺少可验证对象。

---

### 5.2 DD-22 —— MFA Secret 加密方案

#### 方案 A（**推荐**）：AES-256-GCM（AEAD）+ `MFA_ENCRYPTION_KEY` + 版本化密文

```text
密文格式：v1.<base64url(nonce ‖ ciphertext ‖ tag)>
           nonce = 12 字节 CSPRNG（每次加密重新生成）
           tag   = 128 bit
密钥    ：MFA_ENCRYPTION_KEY = base64 的 32 字节（256 bit）
AAD     ：绑定 user_id 与 provider（防跨行替换）
```

| 决策点 | 取值 | 理由 |
|---|---|---|
| 为什么用 AEAD 而非哈希 | **必须可解密还原** | TOTP 类 Provider 需要用 secret **重算**动态码；`argon2` / `bcrypt` 不可逆 → 结构性不可用 |
| 为什么要 AAD 绑定 `user_id` + `provider` | 防止把 A 的密文搬到 B 的行上 | 没有 AAD 时，密文被复制 / 误写到他行后，系统会**用 A 的 secret 正常验证 B 的登录**，且完全无迹可循 |
| 为什么密文带 `v1.` 版本前缀 | 未来换算法 / 换密钥时可**逐行渐进迁移**（读旧写新） | 无需停机全量重加密；也让"密文是哪个格式"可判定 |
| 为什么用 `MFA_ENCRYPTION_KEY` 而非 `ENCRYPTION_KEY` | **域分离**（domain separation） | 一把密钥服务多种用途会扩大泄漏面；`13 §2` 本就把两者列为独立配置项 |
| 密钥缺失 / 长度不符 | **fail-closed**：MFA 读写直接 `ConfigurationError` | **不得**回落明文保存，**不得**回落"跳过 MFA" |
| 解密失败（密钥被换 / 密文损坏） | **拒绝校验 + 记 `MFA_FAILURE`** | 不得静默视为"未启用"——那会把损坏记录变成认证绕过 |
| 密文是否进日志 / 审计 | **否**，只记"已设置 / 未设置" | 密文虽不可读，但写入审计属无必要的敏感面扩大 |

**一并需要冻结的参数**：

| # | 参数 | 草案取值 | 说明 |
|---|---|---|---|
| P1 | 密文列类型与长度 | **`Text`**（不限长） | AEAD 密文 base64 后长度随 Provider 与密钥格式变化；用定长列会埋下**静默截断**风险（截断后解密必失败，且难以定位） |
| P2 | `APP_ENV=prod` 时 `MFA_ENCRYPTION_KEY` 为空 | **启动失败** | 与既有 `ENCRYPTION_KEY` 同口径。⚠️ **现状缺口**：`app/core/config.py::_guard_production_secrets` 只检查 `POSTGRES_PASSWORD` / `REDIS_PASSWORD` / `SIGNING_SECRET` / `ENCRYPTION_KEY`，**未包含 `MFA_ENCRYPTION_KEY`**，本 Phase 需补上；否则"密钥缺失"会从启动期问题变成运行期首次启用 MFA 才暴露 |
| P3 | 密钥轮换 / 多密钥环 | **本 Phase 不实现** | 属 DD-09（Secret Manager，未冻结）。`v1.` 前缀使未来的双密钥读取成为纯增量改动 |
| P4 | 解密后的明文 secret 是否需要显式擦除 | 不强制（Python `str` 不可擦除） | 明确记录该限制，避免产生"已擦除"的虚假安全感 |

#### 方案 B：信封加密（Envelope Encryption）

- 数据密钥（DEK）加密 secret，DEK 再由 `MFA_ENCRYPTION_KEY`（KEK）加密后与密文同存。
- 优点：换 KEK 不需要重新加密全部数据行。
- 代价：本 Phase 引入两把密钥与一层间接，而**密钥管理本身（DD-09）尚未冻结**
  → 现在做等于替 DD-09 做决定，且 Phase 9 大概率会推翻。**不推荐。**

#### 方案 C：数据库侧加密（`pgcrypto` / TDE）

- 密钥会出现在 SQL 语句或 DB 配置中，与 `13 §2` 的"由应用侧注入密钥"取向相反；
  且应用**无法**做完整性校验、**无法**用 AAD 绑定 `user_id`。**不推荐。**

#### 方案 D：不加密，靠列级权限 / 视图保护

- **直接违反** `04 §6`"Secret 必须加密保存"。**禁止。**

---

### 5.3 DD-23 —— MFA 挑战 / 会话续接机制

**张力**：`04 §1` 的顺序图把 `create session` 放在 `MFA check` **之后**，
但 `08 §3` 又要求存在 `POST /auth/mfa/verify`。
"密码已通过、MFA 未完成"的中间态必须有载体，而这载体无 Spec 依据。

#### 方案 A（**推荐**）：登录返回"待验证挑战"，**不建 Session**

```text
POST /auth/login
  密码校验通过 + 策略要求 MFA（且 Provider 可用）
  → 不创建 sessions 行
  → 200 { mfa_required: true, mfa_token: <一次性短寿命令牌>,
          expires_in: 300, provider: "<name>" }

POST /auth/mfa/verify   { mfa_token, code }
  → 校验通过 → 创建 Session + 签发 access / refresh（即"完成登录"）
```

- **依据**：`04 §1` 的顺序图明确"create session 在 MFA check **之后**"；
- **为什么不能提前建 Session**：Phase 4 已实现的在线判定是
  `未撤销 + 会话未过期 + 用户 ACTIVE`，因此提前建的行会让
  "**只输对密码的人**"在后台显示为**在线**——这是一个可直接观察的业务错误；
  更严重的是"认证是否完成"会变成 `sessions` 上的一个**可选列**，
  而任何一条漏检该列的鉴权路径都是**认证绕过**。
  把安全状态放在"默认放行"的位置是不可接受的。
- `mfa_token` **只存哈希**（与 DD-02 的 refresh 同口径），**一次性**，
  校验成功或失败都作废。
- 代价：新增一张挑战表（与 `DD-24` 一并裁定）+ 令牌哈希存储。

#### 方案 B：先建 Session 并标记 `mfa_pending`

- 需给 `sessions`（Phase 4 已验收的表）加列，并让**每一个**鉴权路径都检查该列。
- 风险：漏检一处即认证绕过；且"未完成认证的会话"会出现在在线列表。
- **不推荐。**

#### 方案 C：`/auth/login` 同步阻塞式二次验证（同一请求内两次交互）

- HTTP 无状态，无法在一次请求内要求用户补输入。若改成
  `POST /auth/login {username, password, code}`，则 `08 §3` 的
  `POST /auth/mfa/verify` 失去存在意义 → **与冻结的端点清单冲突**。**不可行。**

#### 方案 D：为挑战复用 `sessions` 并新增 `PENDING` 状态

- 等价于方案 B 的变体，同样的漏检风险。**不推荐。**

#### 需要一并冻结的参数（草案 A 的取值）

| # | 参数 | 草案 A | 理由 |
|---|---|---|---|
| Q1 | `mfa_token` 形态 | 不透明随机串（`secrets.token_urlsafe(32)`，与 DD-02 同口径），**只存哈希** | 与 Phase 4 冻结的令牌口径一致；库内无明文 |
| Q2 | `mfa_token` TTL | **5 分钟** | 足够输入 6 位码；足够短以限制暴力窗口 |
| Q3 | 是否一次性 | **是**：校验**成功或失败**后立即作废 | 失败也作废，避免用同一个挑战无限次试码 |
| Q4 | 挑战失败次数上限 | **5 次**后作废挑战 | 与 `10 §5` 的登录锁定阈值同口径 |
| Q4b | MFA 失败是否计入账号锁定 | **不计入** | `10 §5` 的锁定语义是"**密码**连续失败"。计入会导致"持有正确密码但拿不到动态码"（如手机丢失）的用户被锁在账号外——此时正确处置是走恢复流程，不是锁定。MFA 的防暴力应由**挑战级作废 + rate limit**承担 |
| Q5 | 挑战表归属 | 新表（`DD-24` 一并裁定） | 短期、一次性、可批量清理 |
| Q6 | `/auth/mfa/verify` 的 rate limit | 结构上限：挑战级 5 次作废；**精确阈值属 DD-10（未冻结）** | `10 §6` 要求"应有 rate limit"，但 `16 §10` 把精确阈值列为待冻结项 → 本 Phase 不自造全局阈值，见 `§5.6` |
| Q7 | 挑战期间是否出现在在线列表 | **否**（未建 session） | 与 `04 §5` 的在线语义一致 |

---

### 5.4 DD-24 —— MFA 策略与凭据的存储模型

**未冻结**：`user_mfa` 是每用户一行还是每用户每 Provider 一行；
"是否要求"这一**策略**与"provider + secret"这一**凭据**是否同表；
role 级策略放 `roles` 加列还是独立表；system 级默认放环境变量还是系统参数表。

#### 方案 A（**推荐**）：**"策略"与"凭据"分离，三张表**

```text
mfa_policies     策略（是否要求）     按主体存：subject_type ∈ {USER, ROLE}
user_mfa         凭据（Provider 相关） 按用户 + provider 存
mfa_challenges   挑战（DD-23）        短期、一次性
```

**`mfa_policies`**

```text
subject_type  ENUM(USER, ROLE)         -- 策略作用的**主体类型**
subject_id    BIGINT                   -- 主体 ID（Snowflake）
required      BOOLEAN NULL             -- NULL = 未表态；FALSE = 明确不要求；TRUE = 要求
UNIQUE(subject_type, subject_id)       -- 每主体至多一条策略
```

| 决策点 | 取值 | 理由 |
|---|---|---|
| 为什么不用 `roles.mfa_required` + `admin_users.mfa_required` 两个列 | 拒绝 | `04 §7` 的"策略"是**同一件事**作用于两种主体。两列两处会让"策略来源解析"分叉，且未来新增第三类主体（如部门级策略）就要再加一列 |
| 为什么用 `subject_type + subject_id` 而非两个可空外键 | 拒绝后者 | "两列必有一列 NULL"的可空外键模式约束难写、索引利用率低；且无法用一个唯一约束表达"每主体至多一条" |
| `required` 用 `NULL` 表达"未表态" | **必须可区分** | 与 Phase 4 已固化的语义**逐字对齐**：`UnsetUserMfaPolicySource` 返回 `None`（未表态，继续向下询问）；若合并为 `False`，**用户级实现一旦上线就会永久屏蔽角色级策略**，且运行时完全看不出来 |
| 主体被删除后 | 逻辑删除 + 外键完整性 | 部门 / 用户 / 角色均为逻辑删除（`AGENTS.md §7`），故 `subject_id` 无硬外键约束风险，但**必须**在解析时校验主体有效性 |

**`user_mfa`**

```text
user_id          BIGINT
provider         VARCHAR(32)            -- 与 MfaProvider.name 对齐（Phase 4 已定长度上界）
status           ENUM(DISABLED, SETUP, ENABLED)   -- 复用 Phase 4 的 MfaStatus，不新增枚举
encrypted_secret Text                    -- DD-22 的 AEAD 密文
setup_at / enabled_at / verified_at  TIMESTAMPTZ NULL
UNIQUE(user_id, provider)
```

| 决策点 | 取值 | 理由 |
|---|---|---|
| 唯一键 `(user_id, provider)` | 采用 | 支持同一用户未来从 TOTP **迁移**到 WebAuthn 时两者**并存**，由 `MfaProviderRegistry.active_name` 决定当前生效者（`app/services/mfa.py` 的 `MfaProvider.name` 注释已预留该用途） |
| `status` 是否新枚举 | **复用** `MfaStatus` | `04 §6` 的三态已在 Phase 4 冻结为枚举，重复定义会产生第二份真相 |
| `07 §7` 的字段是否全用 | 采用，另加 `user_id` / `provider` 唯一键 | `07 §7` 明写"**建议**包含"，且"具体字段随 Provider 设计确定" |

**`mfa_challenges`**（DD-23）：见 `4.3` 的 Q1~Q7。

**system 级默认值的归属（跨 Phase 边界，需裁定）**

- `05 §5` 把 "MFA default policy" 列为**系统参数**（须有类型 / 默认值 / 状态 / 描述 / **审计**），
  而系统参数属 **Phase 7**；
- **Phase 4/5 现状**：从环境变量 `settings.mfa_required_default` 读（需重启才生效、无审计）；
- **本草案不改**：`MfaPolicyResolver` 已把 system 级抽象为**构造参数**，
  Phase 7 用参数表实现 `system_default` 后**无需改动任何 MFA 代码**；
- 请裁定：**Phase 5 保持环境变量、Phase 7 迁入系统参数表（推荐）**，
  还是 Phase 5 就地建参数表（会与 Phase 7 的字典 / 参数交付**重叠**，
  并可能造成"两套参数机制"）。

#### 方案 B：策略与凭据合并进 `user_mfa` 一张表

- `user_mfa` 加 `required` 列。
- **问题**：角色级策略**不属于任何用户**，无处安放。
  要么再开一张表（等于回到方案 A 的一半），要么放弃角色级策略（**违反 `04 §7`**）。
- **不可行。**

#### 方案 C：策略全部放环境变量 / 配置文件

- **违反** `04 §7`"按用户配置"（环境变量无法表达每用户策略）
  与 `05 §5` 的系统参数要求。**禁止。**

#### 方案 D：策略放进通用"系统参数"KV（所有层级都塞参数表）

- 参数表适合"系统级单值"。把 user / role 级策略塞进 KV 会失去外键完整性
  （主体被删后留下孤儿策略），且"某角色是否要求 MFA"**无法用 SQL 直查**。
- **不推荐。**

---

### 5.5 裁判第 12 项 —— 无 Spec 依据，请求澄清

**事实**（可复现）：

```text
$ grep -rn "恢复流程\|恢复码\|备用码\|recovery code\|backup code" docs/
docs/verification/005-mfa.md:14:- [ ] 恢复流程不会泄漏 Secret

$ grep -rn "恢复\|recovery\|Recovery" docs/spec/
（无输出）
```

在整个 `docs/` 中，"恢复流程"**只出现在裁判书自己那一行**；
`docs/spec/` 全域对 `恢复` / `recovery` 的检索结果为**空**。

**因此**：Spec 没有定义 MFA 的"恢复流程"（恢复码 / 备用码 / 管理员重置 MFA /
账号找回），也没有规定该流程中 Secret 的处理方式，而裁判项却要求验证它。

**为什么不能自行决定**——三种可能的意图，实现完全不同：

| 可能意图 | 需要的实现 | 与现有 Spec 的关系 |
|---|---|---|
| **(a) 恢复码 / 备用码**：启用 MFA 时生成一批一次性码，设备丢失时使用 | 新增 `mfa_recovery_codes` 表、生成 / 哈希 / 作废 / 消费逻辑、**新端点** | Spec **完全未提及**；`08 §3` 端点清单中**没有**任何恢复端点 → 属**新增业务能力** |
| **(b) 管理员重置 MFA**：管理员为丢失设备的用户重置 MFA 状态 | 可复用"禁用该用户 MFA"路径 + 审计；**新端点** | `08 §4` 无对应端点；Phase 2 有过"由人类裁定补齐端点"的先例（`POST /users/{id}/delete`、`GET / PUT /users/{id}/roles`） |
| **(c) 仅要求"重置 / 查询过程中 Secret 不回显"** | 保证 `GET /auth/mfa` 与所有响应体**不含** `encrypted_secret` 或明文 secret | 与 `00 §1#12` / `10 §4` 同向，属**已冻结义务的表述**，**无需新功能** |

- 若意图是 (a) / (b)：属"新增业务能力"，`AGENTS.md §4` 要求"先停止扩展、记录问题、
  不得自行扩大范围" → 需要人类**授权新增表与端点**；
- 若意图是 (c)：本 Phase 可直接满足，裁判第 12 项判 **PASS**
  （以"响应体不含 secret / 密文"的测试为证据）。

**处置**：在收到澄清前，第 12 项按 **BLOCKED_BY_DESIGN** 记录
（不是环境阻塞，而是"**验收标准缺少 Spec 依据**"），**不判 PASS、不判 FAIL**。

---

### 5.6 Agent 将自行采用并登记的 INTERIM 取值（无需裁定，仅报备）

以下为 Spec 未规定、且**不改变安全语义**的技术默认；若有不同意见请指名否决。

| 位置 | INTERIM 取值 | 说明 |
|---|---|---|
| `/auth/mfa/verify` 限流 | 只实现**结构上限**（每个挑战 5 次失败即作废）；跨挑战的 IP / 用户维度限流**留 Phase 9** | `10 §6` 要求"应有 rate limit"，但精确阈值属 `16 §10`（DD-10）待冻结项；自造全局阈值等于发明业务规则 |
| `GET /auth/mfa` 响应体 | 只返回 `status` / `provider` / `setup_at` / `enabled_at`，**绝不返回** secret、密文或任何恢复材料 | `08 §3` 只给了路径未给响应体；`00 §1#12` 与 `10 §4` 决定其边界 |
| MFA 失败对外文案 | 统一为"验证码无效或已过期" | 与 `10 §5` 的登录失败文案同口径：**不区分**"码错误 / 挑战过期 / 挑战不存在 / 解密失败"；内部原因只写审计 |
| `MfaStatus.SETUP` 的存续期 | **不设超时自动失效**，由用户显式 `enable` 或 `disable` 结束 | `04 §6` 只给三态，未规定 `SETUP` 是否超时。自造超时会引入一个**无人触发的清理任务**；代价是残留的 `SETUP` 记录可能长期存在（属运维可见性，不是安全缺陷） |
| 审计 `resource_type` | `MFA`（与既有 `SESSION` 同构） | `04 §8` 只给事件类别；`06 §2` 的 `resource_type` 取值域未冻结 |
| MFA 事件与既有事件的对应 | `MFA_SETUP` / `MFA_ENABLE` / `MFA_DISABLE` / `MFA_FAILURE` 四个动作**严格对应** `04 §8` 的四项，不新增同义事件 | Phase 4 已登记这些枚举（`app/audit/events.py`），本 Phase 只产生实际记录 |

---

## 6. 裁判项 → 阻塞源 映射表

| # | `005-mfa.md` 验收项 | 阻塞源 | 现状 |
|---|---|---|---|
| 1 | MFA Provider 使用可扩展接口 | **DD-01** | 抽象已交付（Phase 4）；"使用"需要一个可用 Provider |
| 2 | 支持 DISABLED / SETUP / ENABLED 生命周期 | **DD-24**（表结构）+ **DD-01**（字段随 Provider） | 枚举已交付；持久化未做 |
| 3 | Secret 加密保存 | **DD-22** | 无任何加解密设施 |
| 4 | Secret 不进入日志 | — | ✅ 脱敏基建已就绪（`NEVER_LOG_KEYS`）；需在 MFA 链路上验证 |
| 5 | 支持按角色配置 MFA | **DD-24** | ❌ |
| 6 | 支持按用户配置 MFA | **DD-24** | ❌ |
| 7 | 用户级策略优先于角色级策略 | **DD-24** | 解析器已交付；**真实策略源**缺失 |
| 8 | 角色级策略优先于系统默认 | **DD-24** | 同上 |
| 9 | 登录流程正确触发 MFA | **DD-23** | ❌ |
| 10 | MFA enable / disable 有安全日志 | **DD-24** + **DD-23** | 事件枚举已登记；无写路径 |
| 11 | MFA failure 有安全日志 | **DD-23** | 同上 |
| 12 | 恢复流程不会泄漏 Secret | **无 Spec 依据** | 请求澄清（`§5.5`） |
| 13 | 未冻结的 V1 Provider 不得被 Agent 擅自定义为业务事实 | **DD-01** | 依赖裁定结果 |

**统计**：13 项中 **11 项**依赖上述四个裁定；**1 项**（第 4 项）基建已具备，
但需先存在 Secret 才有验证意义；**1 项**（第 12 项）缺少 Spec 依据。

→ **结论：Phase 5 无法在收到裁定前完成，判定 `BLOCKED — NEED USER DECISION`。**

---

## 7. 影响面

| 若批准 | Phase 5 依赖面 | 需新建的产物 |
|---|---|---|
| **DD-01 A** + DD-22 A + DD-23 A + DD-24 A | **零外部设计依赖**（不依赖 Redis、不依赖 Phase 7 参数表） | `mfa_policies` / `user_mfa` / `mfa_challenges` 三表 + Alembic 迁移、`app/core/security/aead.py`（AEAD 封装）、`MfaManagementService`、`/auth/mfa` 等 **5 个端点**、`tests/` 内的测试 Provider、`docs/verification/005-mfa-result.md` |
| **DD-01 B**（冻结 TOTP） | 同上 **+ T1~T6 参数需一并冻结** | 同上 **+** TOTP 实现（或第三方依赖，取决于 `§8` 第 2 问） |
| **DD-01 C**（Email / SMS） | 额外依赖 SMTP / 短信网关 + DD-09 Secret 管理 | 同上 + 投递通道与失败重试 |
| **DD-01 D**（整体延后） | Phase 5 判 BLOCKED；`006` 第 43 行、`009` 第 8 行、`010` 第 18 / 33 行的 MFA 项**连带无法完整验收** | 无 |

---

## 8. 请求裁定清单

请逐条回复（可直接回"**全部批准草案 A**"）：

1. **DD-01**：V1 具体 Provider 选哪一个 ——
   **A**（推荐，最贴合 `PHASES.md`：不选定产品级 Provider，`app/` 内零算法实现，
   测试专用 Provider 用于验收；**残留：生产仍无可用二次验证，需你明确接受**）、
   **B**（推荐备选：**正式冻结 TOTP** 为 V1 Provider，并冻结 T1~T6：
   SHA-1 / 6 位 / 30 秒 / 容错 ±1 步 / 不允许码重用）、
   **C**（Email 或 SMS —— 需外部投递通道，不推荐）、
   还是 **D**（MFA 整体延后，Phase 5 记 BLOCKED）？
2. **DD-01 附带**：若选 A 或 B，**是否允许新增第三方依赖**（例如 TOTP / 加密库）？
   还是要求**零新增依赖**、由项目自行实现（TOTP 约 40 行，AEAD 用标准库即可）？
3. **DD-22**：是否批准 **5.2 方案 A**（AES-256-GCM；密钥来自 `MFA_ENCRYPTION_KEY`
   （base64 的 32 字节）；密文格式 `v1.<base64url(nonce‖ct‖tag)>`；
   AAD 绑定 `user_id` + `provider`；密钥缺失 / 解密失败一律 fail-closed）？
   并确认 **P2**：`APP_ENV=prod` 时 `MFA_ENCRYPTION_KEY` 为空应**启动失败**
   （现状该键**未**纳入 prod 校验，本 Phase 会补上）？
4. **DD-23**：是否批准 **5.3 方案 A**（密码通过后**不建 Session**，
   返回一次性 `mfa_token`：5 分钟、只存哈希、成功或失败即作废；
   `POST /auth/mfa/verify` 完成后才建 Session）？
   并确认 **Q4b**：MFA 挑战失败**不锁定账号**，只作废挑战 + 限流？
5. **DD-24**：是否批准 **5.4 方案 A**（策略与凭据**分表**：
   `mfa_policies(subject_type, subject_id, required)`（`NULL` = 未表态）
   + `user_mfa(user_id, provider, status, encrypted_secret, *_at)`
   + `mfa_challenges`）？
   并裁定 **system 级默认值的归属**：Phase 5 继续读环境变量、
   **Phase 7** 迁入系统参数表（推荐），还是 Phase 5 就地建参数表？
6. **裁判第 12 项**：其"恢复流程"实际指 **(a)** 恢复码 / 备用码、
   **(b)** 管理员重置 MFA、还是 **(c)** 仅要求"重置 / 查询过程中 Secret 不回显"？
   若为 (a) 或 (b)，请说明是否**授权新增表与端点**
   （这会超出现有 `08 §3` 的端点清单）。
7. **`§5.6` 的 INTERIM 取值**：是否接受？如有异议请指名否决。

**在收到裁定前，Phase 5 不进入编码。**

已冻结且不依赖上述裁定的部分（`MfaProvider` 抽象、`MfaStatus` 枚举、
策略优先级解析、脱敏规则、安全日志事件枚举）**已在 Phase 4 交付**；
其余部分若先行实现将产生**确定性返工**（密文格式决定列类型、Provider 选型决定
secret 形态、挑战机制决定登录响应契约、策略模型决定迁移脚本），
故 Agent 选择**等待裁定后一次性实现**。
