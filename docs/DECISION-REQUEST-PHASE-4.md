# BLOCKED — NEED USER DECISION（Phase 4 / Authentication）

> 本文件**不是 Spec**，也不修改任何冻结结论。
> 它是 Agent 在 Phase 4 遇到的**设计阻塞点**的正式决策请求，
> 按 `AGENTS.md §4/§5` 与用户执行协议第七节的要求输出。
>
> 依据用户既有裁定"**由我起草，你审批**"，本文档包含 Agent 起草的**契约草案**。
> 审批通过后，Agent 将按草案实现，并回填 `docs/DESIGN-DECISIONS.md`。

---

## 0. 阻塞总览

| 编号 | 主题 | 阻塞严重度 | 影响的验收项 |
|---|---|---|---|
| **DD-02** | Access Token / Refresh Token 精确生命周期 | **PHASE-4-BLOCKER** | `003 §登录成功创建 Session`、`§Refresh Token 按安全规则保存`、`§Logout 正常失效`；`10 §7`"Revoke 后 Token 必须不能继续访问" |
| **DD-03** | Redis Key 精确命名（含 Session 存储介质） | **PHASE-4-BLOCKER**（若选草案 B/C） | `003 §登录成功创建 Session`、`§Refresh Token 按安全规则保存`；`07 §6` sessions 表 |
| **DD-11** | 幂等 Key 的具体策略 | **PHASE-4-BLOCKER**（`revoke all` 明确被列为幂等场景） | `11 §4`；Phase 4 Session revoke all |
| **DD-01** | V1 具体 MFA Provider（及登录流程 MFA 步骤的 Phase 边界） | **NEED RULING**（非阻塞，但决定 `003 §MFA 检查` 的判定口径） | `003 §MFA 检查`；`04 §1` 流程第 6 步；`04 §6/§7` |

**已冻结、无需裁定且 Agent 可直接实现的部分**（不构成阻塞）：

- 登录流程**步骤与顺序**（`04 §1`）；
- 密码策略全部参数（`00 §2` / `04 §2`：≥12、大小写、数字、特殊字符、最近 5 个不可重复、90 天、5 次失败锁 30 分钟、管理员重置后强制改密）；
- `sessions` 表的**字段清单**（`07 §6` / `04 §3`）与"Refresh Token 哈希存储、不存明文"；
- 登录失败对外文案不得泄露用户是否存在（`10 §5`）；
- 不得记录 password / hash / MFA secret / token 明文（`10 §4`）；
- 安全日志事件清单（`04 §8`）；
- `admin_users` 已有 `failed_login_count` / `locked_until` / `password_changed_at` / `must_change_password` 列；
- 密码哈希算法 = **argon2id**（已裁定），`app/core/security/password.py` 已实现策略常量与哈希器。

> **即：阻塞只来自"Token 生命周期 / 存储介质 / 幂等机制 / MFA 边界"这四类技术设计决策，
> 业务规则本身已完全冻结。**

---

## 1. 问题

Phase 4 要求实现 `login / password policy / failed attempts / lockout / password reset /
forced password change / logout / refresh / me`，并运行 `docs/verification/003-authentication.md`。

Spec 冻结了**流程**与**表字段清单**，但没有冻结**令牌如何构成、活多久、如何失效**。
而 `10 §7` 有一条强要求：

```text
Revoke 后 Token 必须不能继续访问。
Revoke all 后所有对应 Session 都必须失效。
```

这条要求与"无状态 JWT"存在**结构性张力**：自证型 token 在签发后无法被单方面作废，
要实现"revoke 后立即不可访问"，就必须**每次请求回查 Session 状态**（或维护黑名单）。
这个取舍直接决定整个认证子系统的形态，因此**必须由人类裁定，Agent 不得自行选择**。

---

## 2. 当前 Spec 原文（逐条引用）

`docs/spec/04-认证MFA与Session.md`

```text
§1 Login 流程：username/password → user lookup → status check → lock check
              → password verify → MFA check → create session → issue token
              → audit/security log → response
§2 Password：>= 12 / uppercase / lowercase / digit / special /
             last 5 passwords cannot repeat / 90 days /
             5 consecutive failures → 30 minutes lock /
             admin reset → first login force change
§3 Session 必须记录：session id / user id / login time / last active / IP /
             user agent / device / expires_at / revoked_at / revoke_reason /
             token identifiers
   Refresh Token 必须哈希存储，不得保存明文。
§4 Kick：revoke one / revoke all；SUPER_ADMIN 可 revoke 正常用户、
             不能被其他管理员 revoke、仅本人 logout；
             Department Admin 只能 revoke 管理范围内正常用户。
§6 MFA：Provider 必须抽象（setup/verify/enable/disable）；
         生命周期 DISABLED → SETUP → ENABLED；Secret 必须加密保存。
§7 MFA Policy：system default / role policy / user policy；优先级 user > role > system。
   V1 具体 Provider 尚未冻结。
```

`docs/spec/07-数据库设计.md §6`

```text
至少包含：id / user_id / token identifier/hash / login_at / last_active_at /
           ip / user_agent / device / expires_at / revoked_at / revoke_reason
Refresh Token 不保存明文。
```

`docs/spec/10-安全设计.md`

```text
§4 不得记录：password / password hash 到普通业务日志 / MFA secret /
            refresh token plaintext / access token plaintext
§5 - 5 failures → 30 min lock
   - rate limiting 应作为进一步保护
   - 登录失败信息不得泄露用户是否存在等不必要信息
§7 - Revoke 后 Token 必须不能继续访问。
   - Revoke all 后所有对应 Session 都必须失效。
```

`docs/spec/08-API规范.md`（端点清单，请求/响应体未定义）

```text
POST /auth/login    POST /auth/mfa/verify    POST /auth/refresh
POST /auth/logout   GET  /auth/me            GET  /auth/permissions
GET  /auth/mfa      POST /auth/mfa/setup     POST /auth/mfa/enable
POST /auth/mfa/disable
```

`docs/spec/11-缓存并发幂等.md §4`

```text
适用场景：批量操作 / 导入 / Session revoke all / 其他可能重复提交的写操作
具体幂等 Key 在实现阶段确定。
```

`docs/spec/16-完整性检查.md §技术设计待冻结项`

```text
2. Access Token / Refresh Token 精确生命周期
3. Redis Key 精确命名
11. 幂等 Key 的具体策略
（并明确："这些属于技术设计决策，应在实现相应 Phase 前冻结。"）
```

**Spec 全文没有规定**：token 的形态（不透明串 / JWT）、TTL 取值、Refresh 是否轮换、
复用检测策略、传输位置（Header / Cookie）、签名算法、`token identifiers` 的构成、
`device` 的判定来源、在线状态的计算规则、`sessions` 之外是否还要 Redis。

---

## 3. 代码现状

| 能力 | 状态 |
|---|---|
| 密码策略常量与校验 | ✅ 已有：`app/core/security/password.py`（`PASSWORD_MIN_LENGTH=12`、`PASSWORD_HISTORY_SIZE=5`、`PASSWORD_MAX_AGE_DAYS=90`、`MAX_FAILED_LOGIN_ATTEMPTS=5`、`LOCKOUT_MINUTES=30`、`validate_password_policy`） |
| 密码哈希 | ✅ 已有：argon2id（`PasswordHasher` / `get_password_hasher`） |
| 密码历史 | ✅ 已有：`admin_user_password_histories` 表 + `UserRepository.prune_password_history` |
| `admin_users` 锁定列 | ✅ 已有：`failed_login_count` / `locked_until` / `password_changed_at` / `must_change_password` |
| `sessions` 模型与迁移 | ❌ 未创建 |
| MFA 模型（`user_mfa`） | ❌ 未创建 |
| Token 签发 / 校验 | ❌ 未实现（`app/core/security/__init__.py` 明确标注"属后续 Phase"） |
| `SIGNING_SECRET` / `ENCRYPTION_KEY` 配置 | ✅ 已有（`app/core/config.py`，`APP_ENV=prod` 时为空则 fail-closed 启动失败） |
| 审计 / 安全日志基础设施 | ✅ 已有：`AuditRecorder` 端口 + `AuditGuard`；`AuditAction` 枚举（可扩认证事件） |
| 认证相关 HTTP 端点 | ❌ 未实现（Phase 4 范围） |

---

## 4. 为什么阻塞（不能自行决定的具体理由）

1. **"revoke 后 token 立即失效" 决定架构，不是参数**：
   选"无状态 JWT + 不查 Session"会**违反已冻结的 `10 §7`**；
   选"查 Session"则 token 形态、TTL、缓存策略三者耦合，不能分开决定。
2. **TTL 是安全边界**：15 分钟 vs 24 小时的暴露窗口差两个数量级，
   且与 `10 §5` 的 rate limit 取向、`15` 的既有裁定相互影响。
3. **Redis 是否参与**：若 Session 状态进 Redis，就必须同时冻结 Key 命名（DD-03），
   而 DD-03 目前挂 Phase 9；若只用 PostgreSQL，则 Phase 4 可完全不依赖 DD-03。
   **这个选择会改变 Phase 4 的依赖面**，不能由 Agent 单方面扩大或缩小。
4. **`revoke all` 的幂等**：`11 §4` 明确点名该场景，但"具体幂等 Key 在实现阶段确定"
   —— "实现阶段"正是现在，属于 Spec 主动留下的待决项。
5. **`003 §MFA 检查` 的判定口径**：Phase 5 才落地具体 Provider，
   但 Phase 4 的验收里有 MFA 检查项。是否"步骤存在 + 无用户启用即算通过"
   需要人类确认，否则 Agent 要么越界实现 Provider（违反 `16 §1`），
   要么把该项判 BLOCKED（可能不必要地挂起 Phase 4）。

---

## 5. 草案

### 5.1 DD-02 —— Access / Refresh Token 生命周期

#### 方案 A（**推荐**）：不透明 Token + 有状态 Session（PG 为唯一真源）

```text
Access Token  = 256-bit CSPRNG 随机串（不携带任何声明，无自证能力）
Refresh Token = 256-bit CSPRNG 随机串
存储          = sessions.access_token_hash / refresh_token_hash = SHA-256(token)
校验          = 每请求以 access_token_hash 查 sessions → 校验未过期、未撤销
```

| 参数 | 取值 | 理由 |
|---|---|---|
| Access Token TTL | **15 分钟** | 暴露窗口小；配合 revoke 即时生效 |
| Refresh Token TTL | **7 天** | 常见取值，Spec 未规定 |
| Refresh 轮换 | **每次 refresh 都轮换**，旧 token 立即失效 | 缩短被窃取窗口 |
| 复用检测 | 已轮换的 refresh token **再次被使用** → 判定为盗用 → **撤销该 session 的全部 token**（family revocation） | 这是"哈希存储 + 轮换"的意义所在；否则轮换只是形式 |
| 传输 | Access：`Authorization: Bearer <token>`；Refresh：`POST /auth/refresh` 请求体（**草案**，见下 Q3） | — |
| 签名算法 | **不需要**（token 本身无声明，不可伪造，无签名必要） | 也就不存在"算法混淆"类漏洞 |
| 时钟 | 无时钟敏感点（`expires_at` 在 DB 里，按 UTC 比较） | — |
| 撤销语义 | 改 `sessions.revoked_at` 即**立即**生效，无需黑名单 | **直接满足 `10 §7`** |

**优点**：与 `10 §7` 天然一致；不需要 denylist；`07 §6` 列出的每个字段都有明确用途；
`10 §4`（不记录 token 明文）与 `04 §3`（refresh 哈希存储）自然满足（库里只有哈希）；
无签名密钥轮换问题。

**代价**：每请求一次 `sessions` 查询。Phase 3 已裁定"不引入缓存"，
Phase 9 再引入 Redis 只读缓存 —— 依赖面与既有裁定**一致**。

#### 方案 B：JWT Access Token + 每请求仍校验 Session

- Access Token 是 JWT（`sub` / `sid` / `jti` / `iat` / `exp`），
  但**仍**每请求查 `sessions.revoked_at` → 与 A 的查询次数相同，
  只是把不必要的信息放进了 token。
- 除非**豁免** `10 §7`（允许 TTL 内继续访问），此时才真正减少查询 ——
  但那是**放松已冻结的安全要求**，需要人类显式豁免。
- 额外负担：密钥管理（`SIGNING_SECRET`）、算法固定（HS256 且禁用 `none`/RS 混淆）、
  时钟偏移容忍度、密钥轮换策略。

#### 方案 C：JWT + Redis denylist（`jti` 黑名单）

- revoke 时把 `jti` 写入 Redis，TTL = token 剩余寿命。
- **依赖 Redis 可用性**：Redis 不可用时要么 fail-open（违反 `10 §7`，危险）
  要么 fail-closed（认证全站不可用）。同时立刻引入 DD-03（Key 命名）。
- 只在"必须无状态 + 必须支持撤销"的场景有价值；本项目的 `sessions` 表
  本来就要求持久化，因此该方案是**多余的一层**。

#### 无论选哪个方案，以下参数都需要一并冻结（草案 A 的取值）

| # | 参数 | 草案 A |
|---|---|---|
| P1 | Access Token TTL | 15 min |
| P2 | Refresh Token TTL | 7 天（固定，不滑动） |
| P3 | Refresh 轮换 | 每次轮换 |
| P4 | 复用检测动作 | 撤销整个 session（含 access token） |
| P5 | `sessions` 是否需要 `access_token_hash` 单列 | 需要（否则无法按 token 反查） |
| P6 | Refresh Token 传输位置 | 请求体（Q3 需裁定 Cookie 方案） |
| P7 | 并发 refresh（同一 token 被并发提交两次） | 第一次成功、第二次按"复用"处理会误伤 → 需裁定：加短锁串行化，或允许 N 秒宽限 |
| P8 | 密码 90 天到期后的行为 | 允许登录但**强制改密**（与 `must_change_password` 同一路径）—— 而非直接拒绝登录（草案，需确认） |

---

### 5.2 DD-03 —— Redis Key 命名 / Session 存储介质

#### 方案 A（**推荐**）：Phase 4 **不使用 Redis**，PG 为唯一真源

- `sessions` 表承载全部状态；在线状态按 `last_active_at` + `expires_at` + `revoked_at` 计算。
- **Phase 4 因此完全不依赖 DD-03**，DD-03 继续留给 Phase 9（届时只读缓存）。
- 与 Phase 3 已裁定的"不引入缓存"同向，不引入新的失效面。

#### 方案 B：PG + Redis 双写（在线状态 / 最后活动走 Redis）

- 需要**立即冻结** Redis Key 命名（DD-03）：建议 `vctn:session:{session_id}`、
  `vctn:user:{user_id}:sessions`、`vctn:token:{sha256}`，统一 `vctn:` 前缀 + TTL。
- 代价：双写一致性（Redis 与 PG 分歧时谁是真相？）、Redis 不可用时的降级行为。

#### 方案 C：Session 全部存 Redis

- **与 `07 §6` 冲突**：Spec 明确要求 `sessions` 表及其字段（含 `revoked_at`、
  `revoke_reason` 这类需要长期留存的审计信息）。不推荐。

---

### 5.3 DD-11 —— 幂等 Key 的具体策略（Phase 4 部分）

#### 方案 A（**推荐**）：语义幂等，不引入 `Idempotency-Key` 头

| 端点 | 幂等实现 |
|---|---|
| `POST /auth/logout` | 语义幂等：已失效的 token 再次 logout 返回成功（不报 401） |
| `Session revoke one` | 语义幂等：已撤销的 session 再次 revoke 返回成功 |
| `Session revoke all` | 语义幂等：重复调用结果相同（`revoked_at` 已是同一状态） |
| `POST /auth/refresh` | 由 **rotation + 复用检测**（P3/P4）天然防重放 |
| `POST /auth/login` | 由 lockout 计数天然限流；重复提交是正常的（用户重试） |

- **不引入** `Idempotency-Key` 头与去重存储 → Phase 4 因此**不依赖 Redis**（与 DD-03 方案 A 一致）。
- 通用幂等机制（批量操作 / 导入）留待 Phase 9 与 DD-11 一并冻结。

#### 方案 B：引入 `Idempotency-Key` 头 + Redis 去重

- 需同时冻结 DD-03 的 key 命名与 TTL；扩大了 Phase 4 的依赖面与故障面。

#### 方案 C：所有写端点加 PG 幂等表

- 与 `11 §4` 的适用范围（批量 / 导入 / revoke all / 其他）相比属**过度扩张**，
  且认证热路径多一次写库。

---

### 5.4 DD-01 —— V1 MFA Provider 与登录流程 MFA 步骤的边界

#### 方案 A（**推荐**）：Phase 4 落地"步骤 + 抽象 + fail-closed 默认"，Provider 留 Phase 5

- 实现 `MfaProvider` 抽象接口（`setup` / `verify` / `enable` / `disable`）
  与生命周期 `DISABLED → SETUP → ENABLED`（`04 §6`）；
- 实现 `MfaPolicy` 的 `user > role > system` 优先级解析（`04 §7`）；
- **未配置任何具体 Provider 时**：所有用户 MFA 状态视为 `DISABLED`，
  登录流程的 `MFA check` 步骤**按策略执行但直接通过**（步骤存在、可观测、可扩展）。
- 需要人类确认的判定口径：
  `003 §MFA 检查` → **PASS**（步骤存在且按策略执行；因 V1 Provider 未冻结，
  无用户处于 ENABLED，故无二次验证要求）。
- 收益：Phase 5 落地具体 Provider 时**无需改动登录流程**。

#### 方案 B：Phase 4 完全不碰 MFA

- `003 §MFA 检查` 判 **BLOCKED**（等 Phase 5），Phase 4 无法一次通过验收。

#### 方案 C：Phase 4 自行选定 TOTP 作为 V1 Provider

- **明确禁止**：违反 `16 §技术设计待冻结项 #1` 与用户指令。

---

### 5.5 Agent 将自行采用并登记的 INTERIM 取值（无需裁定，仅报备）

以下为 Spec 未规定、且不影响安全语义的技术默认值；若人类有不同意见可直接否决。

| 位置 | INTERIM 取值 | 说明 |
|---|---|---|
| `sessions.device` | 从 `User-Agent` 做**启发式粗分类**（设备类型 / 操作系统 / 浏览器），不引入第三方解析库 | `04 §3` 只要求"记录 device"，未规定来源。**明确不作为任何安全依据**，仅用于后台展示 |
| 锁定计数清零 | 登录**成功**时清零 `failed_login_count`；`locked_until` 到期即自动解锁（不需要后台任务） | `04 §2` 只说"5 consecutive failures"，未说清零时机；"consecutive"语义要求成功即清零 |
| 达到阈值时的计数 | 设置 `locked_until = now + 30min` 并**保留**计数（不清零） | 避免"锁定期内计数被重置 → 解锁后立即再获 5 次尝试" |
| 登录失败响应 | 对外文案**统一**为"用户名或密码错误"（不区分用户不存在 / 密码错 / 被锁定）；**审计与安全日志**中区分三类原因 | `10 §5` 只要求不泄露用户是否存在；审计侧必须可诊断 |
| 安全日志事件命名 | 扩展现有 `AuditAction` 枚举（`AUTH_LOGIN_SUCCESS` / `AUTH_LOGIN_FAILURE` / `AUTH_LOCKOUT` / `AUTH_PASSWORD_RESET` / `AUTH_PASSWORD_CHANGE` / `AUTH_MFA_*` / `AUTH_SESSION_REVOKE`），事件清单严格对应 `04 §8` | 复用 Phase 1 已交付的审计基础设施，不新建日志框架 |
| 认证端点前缀 | `/api/v1/auth/*`（与既有 `/api/v1/admin/*` 区分） | `08 §` 只给了 `/auth/*`；既有管理端点都在 `/api/v1/admin/**`，认证端点不属于 admin 域 |
| 密码 90 天 | 到期**不拒绝登录**，而是置 `must_change_password = True` 后走强制改密路径 | 避免"旧密码用户被完全锁在门外"（需人类确认，见 P8） |

---

## 6. 影响面

| 若批准方案 | Phase 4 依赖面 | 需新建的产物 |
|---|---|---|
| DD-02 方案 A + DD-03 方案 A + DD-11 方案 A + DD-01 方案 A | **零外部设计依赖**（不依赖 Redis，不依赖 Phase 9 的 DD-03/DD-11） | `sessions` 表与迁移、`user_mfa` 表与迁移、token 生成/哈希模块、`AuthService`、`SessionService`、`MfaPolicyResolver`、认证端点、`docs/verification/003-authentication-result.md` |
| 任一方案选 B / C | Phase 4 将**额外依赖** DD-03（Redis Key 命名）与 Redis 可用性 | 同上 + Redis 客户端与 Key 常量模块 |

---

## 7. 请求裁定清单

请逐条回复（可直接回"全部批准草案 A"）：

1. **DD-02**：是否批准 **5.1 方案 A**（不透明 Token + 有状态 Session，PG 唯一真源；
   Access 15 min / Refresh 7 天 / 每次轮换 / 复用即撤销整个 session）？
   若否，请选 B 或 C，并**明确是否豁免 `10 §7`**（revoke 后 TTL 内仍可访问）。
2. **DD-02 P7**：并发 refresh 如何处理 —— 串行化（推荐）还是允许 N 秒宽限？
3. **DD-02 P8**：密码 90 天到期后是"允许登录但强制改密"（推荐）还是"直接拒绝登录"？
4. **DD-02 P6**：Refresh Token 放在**请求体**（推荐）还是 `HttpOnly` Cookie？
5. **DD-03**：是否批准 **5.2 方案 A**（Phase 4 不使用 Redis，DD-03 继续留 Phase 9）？
6. **DD-11**：是否批准 **5.3 方案 A**（语义幂等，不引入 `Idempotency-Key` 头）？
7. **DD-01**：是否批准 **5.4 方案 A**（Phase 4 落地 MFA 步骤与抽象 +
   fail-closed 默认），并确认 `003 §MFA 检查` 按"步骤存在且按策略执行"判 **PASS**？
8. **5.5 的 INTERIM 取值**：是否接受？如有异议请指名否决。

**在收到裁定前，Phase 4 不进入编码。** 已冻结、不依赖上述裁定的部分
（如 `sessions` / `user_mfa` 的字段清单、密码策略与历史、锁定计数语义）
可以先行落地，但为避免二次返工（token 形态会反向决定表的索引与列），
Agent 选择**等待裁定后一次性实现**。
