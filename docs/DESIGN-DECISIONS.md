# 未冻结设计决策登记表（Design Decision Register）

> 本文件**不是 Spec**，也不修改任何冻结结论。
> 它是 Agent 侧的**登记台账**：记录哪些设计点尚未冻结、当前实现采取了什么
> 临时措施（INTERIM）、以及被推迟到哪个 Phase 处理。
>
> 一旦对应 Spec 冻结，应回填"冻结依据"，并同步移除代码中的 `INTERIM` 标注。
> 冻结业务规则的唯一权威来源始终是 `docs/spec/`。

---

## 1. 登记状态总览

| 编号 | 主题 | 当前状态 | 目标 Phase |
|---|---|---|---|
| **DD-01** | **MFA Provider** | **部分冻结（方案 A，2026-09-24）**：Phase 4 落地登录步骤 + Provider 抽象 + fail-closed。**「具体 Provider 选型」本身仍未冻结** → **阻塞 Phase 5** | **Phase 5（待裁定）** |
| **DD-02** | **Token 生命周期** | **已冻结（方案 A，2026-09-24）** | ✅ Phase 4 |
| **DD-03** | **Redis Key 命名** | 未冻结（Phase 4 已裁定**不使用 Redis**，继续留 Phase 9） | Phase 9（009） |
| DD-04 | Permission Version 缓存语义 | 未冻结（Phase 3 **已落地单调版本号**，缓存语义待定） | Phase 9（009） |
| **DD-05** | **角色继承（Role Inheritance）存储与展开** | **已冻结（方案 A，2026-09-24）** | ✅ Phase 3 |
| **DD-06** | **Field Permission 表结构** | **已冻结（专用表 + 最宽松者胜，2026-09-24）** | ✅ Phase 3 |
| **DD-07** | **CUSTOM Data Scope 的持久化模型** | **已冻结（方案 A，2026-09-24）** | ✅ Phase 3 |
| DD-08 | 日志分区策略 | DEFERRED | Phase 6（006） |
| DD-09 | Secret Manager | 未冻结 | Phase 9（009） |
| DD-10 | Rate Limit 阈值 | 未冻结 | Phase 9（009） |
| **DD-11** | **幂等策略** | **已冻结（方案 A，2026-09-24）**：语义幂等，不引入 `Idempotency-Key` 头 | ✅ Phase 4 |
| DD-12 | 错误码段位表 | 未冻结（现用集中式 INTERIM 码） | 待定 |
| DD-13 | 分页协议 | 未冻结（现用 `pageNum`/`pageSize` + `{list,total,...}` 临时协议） | 待定 |
| DD-14 | Snowflake 参数（epoch / 机器位分配） | 未冻结（现用默认参数） | 待定 |
| DD-16 | 版本策略 | 未冻结 | 待定 |
| DD-18 | PostgreSQL / Redis 镜像版本 | 未冻结（本地不装 Docker，仅交付部署产物） | 待定 |
| **DD-19** | **多角色数据范围的合并规则** | **已冻结（求并 / 最宽，2026-09-24）** | ✅ Phase 3 |
| **DD-20** | **权限资源模型与资源 CRUD 契约（= CONFLICT-001）** | **已冻结（方案 A，2026-09-24）** | ✅ Phase 3 |
| **DD-21** | **无有效角色用户的有效权限上下文表示** | **未冻结（Phase 3 新发现 FINDING-3-01）** | **Phase 8 之前必须裁定** |
| **DD-22** | **MFA Secret 加密方案**（算法 / 密文格式 / 密钥来源与轮换） | **未冻结（Phase 5 新发现）→ 阻塞 Phase 5** | **Phase 5（待裁定）** |
| **DD-23** | **MFA 挑战与会话续接机制**（`/auth/login` → `/auth/mfa/verify` 的中间态载体） | **未冻结（Phase 5 新发现）→ 阻塞 Phase 5** | **Phase 5（待裁定）** |
| **DD-24** | **MFA 策略与凭据的存储模型**（user / role 策略落在哪、凭据表形态） | **未冻结（Phase 5 新发现，源于 `07 §7`「具体字段随 Provider 设计确定」）→ 阻塞 Phase 5** | **Phase 5（待裁定）** |

---

## 2. Phase 3 裁定（人类已裁定，2026-09-24）

> 本节结论**取代**此前"DD-05 保持未冻结"的记录（见 §5 历史沿革）。
> 四条草案均由 Agent 起草、人类逐条批准，属于"人类裁定"而非 Agent 自决。

### DD-20 / CONFLICT-001 权限资源模型 —— 已冻结（方案 A）

- **裁定**：统一 `permission_resources` 表 + 显式类型专属列 + CHECK 约束
  + 独立 `menu_pages` 关联表 + 统一 `role_permissions`；
  `resource_code` **按类型**做逻辑删除感知唯一。
- **批准内容**：方案 A（统一资源表 + 显式列 + CHECK）、资源 CRUD 服务契约、
  声明式 API 绑定（`ApiPermissionCode`）。
- **实现证据**：
  - 迁移 `phase3_dd20`（`down_revision = phase3_dd07`），创建
    `permission_resources` / `menu_pages` / `role_permissions` /
    `role_field_permissions` / `role_inheritances` / `permission_versions`；
  - `app/models/permission.py`；`app/services/permission_resource.py`；
    `app/services/role_permission.py`；`app/schemas/permission.py`；
  - 三类约束已在真库以 `pg_constraint` / `pg_indexes` 复核。
- **CONFLICT-001 状态**：**设计已关闭**。原先"权限资源 Page/Menu/Button/API/Field
  缺定义入口"的冲突，其**模型与契约**已冻结并落地为可用的服务层定义能力。
  资源 CRUD 的 **HTTP 端点暴露**属 `docs/verification/008`
  （Dynamic Frontend Permission Contract）的交付范围，不是本冲突的未决部分。
- **未删除、未弱化**：本冲突以"冻结契约"方式关闭，未删除冲突条目、
  未弱化资源模型、未以临时 API 或硬编码权限资源绕过。

### DD-05 角色继承 —— 已冻结（方案 A）

- **裁定**：邻接表 `role_inheritances(parent_role_id, child_role_id)`
  + 写入期环检测 + 递归 CTE(`UNION`) 展开 + 深度上限 32
  + 删除被引用角色时拒绝。
- **方向（冻结语义）**：`child 继承 parent`，即
  `有效角色 = 直接角色 ∪ 其全部祖先角色`。
- **三重环路防护**（`03 §4`"循环继承 / 无限递归"）：
  1. 数据库 CHECK `no_self_inheritance` 阻止自环；
  2. 写入期检测（`_assert_no_cycle`）：`child ∈ ancestors(parent)` → 409。
     这是唯一能在**入库前**拦住环的地方；
  3. 读取期：递归 CTE 用 `UNION`（去重）→ 已存在的环必然收敛；
     外加深度上限把异常长链暴露为错误而非静默接受可疑结果。
- **实现证据**：`app/models/role.py:130`；`app/repositories/permission.py:745`；
  `app/services/role_inheritance.py`；`tests/test_role_inheritance.py`（28 例）。
- **2026-09-24 修正**：此前"保持未冻结 → BLOCKED"的记录**已作废**。
  `002-permission.md` 的 "Role inheritance V1 生效" 现判定 **PASS**。

### DD-06 Field Permission 表结构 —— 已冻结（专用表 + 最宽松者胜）

- **裁定**：专用 `role_field_permissions(role_id, field_id, access_level)` 表；
  多角色合并取**最宽松者胜**，序为
  `HIDDEN < READ_ONLY < VISIBLE < EDITABLE`。
- **为什么必须专用表**：`03 §9` 的字段权限是**四级有序取值**而非"有 / 无"。
  用二元表承载会丢失等级（等于把 HIDDEN 与 EDITABLE 视为相同），
  直接违反"最终字段策略必须由后端统一计算"的冻结要求。
- **显式后果（不得被当成缺陷改掉）**：在"最宽松者胜"方向下，
  `HIDDEN` **不能**否决其他角色的 `VISIBLE`。该方向与 `00 §1#2`"权限取并集"同向。
  若业务后续要求"HIDDEN 一票否决"，必须重新裁定并改测试。
- **实现证据**：`app/models/enums.py`（`_FIELD_ACCESS_RANK`、
  `most_permissive_field_level` 为**唯一**合并实现）；`tests/test_permission_resources.py::TestFieldLevelMerge`；
  `tests/test_effective_permission.py::TestFieldPermissionMerge`。

### DD-19 多角色数据范围的合并规则 —— 已冻结（求并 / 最宽）

- **裁定**：按**可见集合求并**（最宽）合并。规则：
  ```text
  ALL                  ∪ 任意 = ALL（全局）
  DEPARTMENT_CHILDREN(d) ∪ CUSTOM{c} = {d 及后代} ∪ {c}
  SELF                 ∪ 其他 = 其他可见集合 **外加** actor 本人
  ```
- **批准的修正项**：`ResolvedScope` 新增 `include_self` 字段。
  既有的 `restrict_to_actor` 是"**仅**本人"语义，**无法**表达"部门集合 ∪ 本人"。
  `include_self` 只做**加法**（增加"本人"一条记录），
  从**不放宽**部门维度。
- **为什么"部分 SELF"不能简化为"忽略 SELF"**：忽略会让 SELF 角色表达的
  "只允许看自己"在合并后失去意义；也不能简化为"仅本人"，那会缩小可见性。
- **实现证据**：`app/core/scope.py::ResolvedScope.merge`；
  `app/repositories/scope_filters.py::user_scope_condition`；
  `tests/test_resolved_scope.py::TestResolvedScopeMerge`、`TestIncludeSelfSemantics`；
  `tests/test_scope_guard.py::TestIncludeSelfScopeCondition`（security）。

### DD-07 CUSTOM Data Scope —— 已冻结（实施完成）

- **裁定**：采用 `roles.data_scope` 列 + `role_custom_scope_departments` 子表。
- **实现**：迁移 `phase3_dd07`；`Role.data_scope`（VARCHAR(32) + CHECK 五值，
  默认 `DEPARTMENT_CHILDREN`）；`RoleCustomScopeDepartment`（复合主键
  `(role_id, department_id)`，双 FK `RESTRICT`）。
- **关键不变量**：非 CUSTOM 角色**必须**清空关联表残留行，
  否则改回 CUSTOM 时静默继承过期集合 = 权限放大（Spec `11 §5`）。
  由 `RoleDataScopeService` 保证，并有专门测试钉住。
- **Phase 2 的禁止项已解除**：不再依赖"外部传入 `department_ids`"。

### DD-03 / DD-04 —— Phase 3 不启用权限缓存

- **裁定**：Phase 3 **不引入 Redis 权限缓存**，权限上下文每请求实时计算。
- **理由**：天然满足"权限修改立即生效"（`00 §1#5`），无陈旧缓存放大风险，
  符合 Spec `11 §5`"宁可短暂 cache miss"。
- **本 Phase 已落地的部分**：`permission_versions` 表提供**单调递增**版本号
  （`UPDATE ... SET version = version + 1`，行级锁；绝不是"读出来 +1 再写回"，
  后者并发下会产生重复版本号）。所有改变权限的写路径均递增版本。
- **遗留**：Redis Key 命名（DD-03）与缓存失效机制（DD-04）留待 Phase 9。
- **后果**：`002-permission.md` 的 "缓存失效后新权限立即可见" 判定为
  **PASS（带 Phase 边界说明）** —— 可观测要求（新权限立即可见）已满足，
  缓存失效**机制**本身未实现（且 Phase 3 无缓存需要失效）。

### AuthorizationService 授权口径 —— INTERIM 已解除

- **裁定**：`assert_can_manage_roles` 由 Phase 2 的 INTERIM"仅 SUPER_ADMIN"
  改为基于 API Permission 判定（`ApiPermissionCode.ROLE_MANAGE`）；
  SUPER_ADMIN 走集中式 bypass（`10 §3`）。
- **违反即事故的边界**：业务 Service 中仍**不得**出现 `if actor.is_super_admin`
  分支。`is_super_admin` 判定只允许出现在集中式授权层。
- **验收**：`grep -rn "is_super_admin" app/services/` 仅命中
  `authorization.py` 与 `effective_permission.py`（`PermissionContext`），
  业务 Service 内 0 处。

---

## 3. Phase 3 新登记的未冻结项

### DD-21 无有效角色用户的有效权限上下文表示 —— 未冻结（**Phase 8 之前必须裁定**）

- **来源**：本次执行中发现，登记为 `FINDING-3-01`。
- **问题**：Spec `11 §5` 只要求 fail-closed，未规定"解析不出任何范围"时
  **如何表示**。当前实现存在三种边界、两种表示：
  | 情形 | 当前行为 |
  |---|---|
  | 用户**无任何有效角色**（无角色 / 角色全禁用 / 角色已删除） | `EffectivePermissionService.build()` 抛 `ValueError` |
  | 同一情形走轻量路径 `resolve_api_codes()` | 返回**空集合**（不抛错） |
  | 用户有角色但范围为空（如 CUSTOM 未配置） | 返回合法的**空集合** `ResolvedScope`（拒绝一切） |
- **为什么不能自行决定**：三种都拒绝，安全性无差异；但可观测行为不同 ——
  Phase 8 的 HTTP 层会分别得到 **500** 与 **403 / 空权限**。
  "未配置角色的正常用户是否应该看到 500"是产品语义问题，不是实现细节。
- **Phase 3 处理**：**不改**。保持 fail-closed 现状，用特征化测试钉住，
  并在交付报告中显式登记（当前无 HTTP 层，不存在实际 500）。
- **需要人类裁定**：是否统一为"返回拒绝型权限上下文（空权限 + 空范围）"，
  使 `build()` 成为全函数；还是保留抛错并由 HTTP 层映射为 403。
- **证据**：`tests/test_effective_permission.py::TestDisabledRolesAreExcluded`、
  `::test_role_less_user_fails_closed_with_error`。

### CONFLICT-001 —— 已关闭（设计冻结）

见 §2 DD-20。关闭方式为**冻结契约**，非删除冲突、非弱化模型、非临时 API 绕过。

---

## 4. Phase 3 期间新增的 INTERIM 取值与技术默认

| 位置 | 取值 | 说明 |
|---|---|---|
| `app/services/authorization.py::ApiPermissionCode` | `ROLE_MANAGE` / `PERMISSION_RESOURCE_MANAGE` / `PERMISSION_PREVIEW` | `resource_code` 的字面量命名规范（大小写、分隔符、前缀）Spec 未冻结。集中单点定义，DD 冻结后只改一处；同时是 Phase 8 声明式绑定的入参 |
| `app/models/role.py::RoleInheritance` | 继承关系表**硬删除**（无 `deleted_at`） | 关联表不是独立业务实体，而是实体间关系；为其引入软删除会让唯一约束与"重新授予"语义复杂化（与 `user_roles` 同一口径） |
| `app/repositories/permission.py::GLOBAL_SCOPE` | 版本桶仅使用 `"GLOBAL"` | DD-04 未冻结分桶规范；本 Phase 只提供一个全局桶 |
| `app/services/effective_permission.py::MAX_ROLE_INHERITANCE_DEPTH` | 深度上限 **32** | 正常组织结构不可能达到；达到即基本可断定存在环。超限抛错（fail-closed）而非静默接受 |
| `app/services/role.py` | `role_code` **不可**通过 `PUT /roles/{id}` 修改 | 编码是稳定标识（SUPER_ADMIN 判定、API 资源引用、审计检索均依赖）。改码会引入"把 SUPER_ADMIN 改名为其它码 → 系统静默失去超管入口"这类跨模块后果；需要改码应新建角色并迁移 |
| `app/services/role.py` | **新建角色不递增**权限版本 | 新角色尚无用户持有、无授权，不改变任何人的权限；递增会造成无意义的版本抖动 |
| `app/services/role.py` | 角色删除策略：**他人的依赖 → 拒绝（409）**（`user_roles` / `role_inheritances`）；**自己的从属 → 清理**（`role_permissions` / `role_field_permissions` / CUSTOM 行） | 拒绝优于静默级联：拒绝是显式的，级联是隐式的。清理的是"无主的僵尸授权"，不改变其他实体权限 |
| `app/services/permission_resource.py` | 资源删除：有子资源 / 菜单关联 / 角色授权 → 拒绝（409） | 物理删除会静默改变已配置的权限结构 |
| `app/services/role_permission.py` | 授权写入为**整体替换**（`PUT` 语义，`{"resourceIds": [...]}`） | 幂等、可审计（before/after 完整）。**最易写错处**：替换必须限定在单一资源类型内，否则一次改页面权限会静默清掉 API/BUTTON 授权 —— 已有专门回归测试 |
| `app/services/role_data_scope.py` | 非 CUSTOM 携带 `department_ids` → **拒绝** | 静默丢弃会造成"以为已限定、实际未限定"的错觉 |
| `app/services/role_data_scope.py` | 清空 CUSTOM 后策略降级为 **SELF** | 保留 CUSTOM 会得到"空集合"这种自相矛盾的配置；降级到最小合法策略既不放权也保持自洽 |
| `app/services/role_data_scope.py` | CUSTOM 部门只校验**存在且未删除** | 是否必须落在操作者范围内 Spec 未规定，不得自行外推 |
| `app/services/audit_guard.py` | 只有 **403（权限拒绝）与 409（状态冲突）** 记 FAILURE 审计；400（参数错误）与 404 不记 | 把正常输入校验记成 FAILURE 会淹没真实安全信号，削弱审计价值 |
| `app/services/permission_resource.py` | FIELD 用 `owner_resource_id` 而非 `parent_id` 表达归属 | `parent_id` 语义是"权限树上的父子"，参与树遍历；混用会让"展开页面子树"把字段一并带出，污染树结构 |

---

## 5. 历史沿革（保留以便追溯，不得据此实现）

### Phase 2 收尾（2026-09-23）的裁定 —— 其中 DD-05 已被 §2 取代

| 编号 | Phase 2 裁定 | 现状 |
|---|---|---|
| DD-05 | DEFERRED TO PHASE 3（Phase 2 不建 `role_inheritances`） | **已被 §2 取代**：Phase 3 已冻结并实现 |
| DD-07 | DEFERRED TO PHASE 3（Phase 2 只提供 CUSTOM 算法占位） | 已完成（§2） |
| DD-08 | DEFERRED（不实现日志分区，且**不得**因此修改既有日志行为） | 仍有效，Phase 6 处理 |

### ~~"DD-05 保持未冻结 → BLOCKED"~~（**已作废**）

> 曾有一版记录称人类选择"保持未冻结"，因而 `002-permission.md` 的
> "Role inheritance V1 生效" 与 `PHASE-003-PERMISSION.md` 的
> "Role Inheritance / Circular Inheritance Protection" 判定为未通过。
> **该结论已作废**：人类随后批准 DD-05 方案 A（见 §2）。
> 本 Phase 已实现存储、展开、三重环路防护、权限并集与审计，判定 **PASS**。

### ~~CONFLICT-001 "契约内容尚未提供"~~（**已作废**）

> 曾有一版记录称"人类选择冻结契约但内容尚未提供，因此 Task 3.6~3.9、3.11
> 仍为 `BLOCKED — CONFLICT-001`"。**该结论已作废**：DD-20 方案 A 已获批并落地
> （见 §2），相关任务全部完成。

---

## 6. 需要关注的风险与行为外推

### RISK-004 SUPER_ADMIN 判定口径与权限并集口径不一致 —— 未修复，已登记

- **现状**：`is_super_admin` 由 `RoleRepository.list_role_codes_for_user` 推导，
  该查询**只过滤 `deleted_at`、不过滤 `status`**；
  而权限并集（`list_active_role_ids_for_user`）**会**过滤 `ACTIVE`。
- **后果**：持有**被禁用的** SUPER_ADMIN 角色仍被当作 SUPER_ADMIN，
  从而获得全局数据范围与全部 API 权限（`has_api_permission` 直接放行）。
- **为什么不自行修改**：这是已冻结集中式规则的**语义变更**
  （"禁用角色"是否也应剥夺 SUPER_ADMIN 身份），不属于本 Phase 可自决范围。
- **处理**：以特征化测试钉住现状，使任何修改都会**显式失败**而非被悄悄改掉。
- **证据**：`tests/test_effective_permission.py::TestRisk004Characterization`（2 例）；
  `app/services/authorization.py` 模块级风险说明。

### FINDING-4-01 `authenticate()` 的 refresh 过期判定不可达 —— 有意保留

- **现状**：DEFECT-4-01 修复后，`expires_at <= refresh_expires_at` 由
  `sessions` 上的 CHECK 强制、且由 `SessionService.rotated_access_expiry`
  构造性保证，因此 `SessionService.authenticate` 中
  `or session.is_refresh_expired(checked_at)` 这一支**必然冗余** ——
  不存在能触发它的合法数据状态，**该分支无法被测试覆盖**。
- **为什么不删**：这是**安全判定的冗余**，与业务判定的冗余价值不同。
  一旦将来有人放宽或移除那条 CHECK（例如 DD-02 若改判为滑动续期），
  少写这一个 `or` 就会把"会话总寿命是硬上界"静默变成一句空话。
  删掉它能让用例更好写，代价是删掉一条安全性质 —— 不划算。
- **处理**：保留，并在代码注释与验收报告中显式说明"该分支不可达且无覆盖"，
  避免后续评审把它误判为"漏测"。
- **证据**：`app/services/session.py:196`；
  `docs/verification/003-authentication-result.md §4`。

### Phase 2 已裁定的行为外推（延续有效）

| 项 | Spec 原文范围 | 本次实现 | 状态 |
|---|---|---|---|
| 创建用户时 `must_change_password` | `00 §2` 只规定"管理员**重置**密码后"必须改密 | 创建同样置 `True` | 已裁定（RISK-001） |
| 禁用 / 删除**最后一个** SUPER_ADMIN | `00 §1#7` 只规定"其他管理员不能踢 SUPER_ADMIN" | 禁止禁用 / 逻辑删除最后一个，且记 FAILURE 审计 | 已裁定（RISK-002） |
| 响应返回真实手机号 / 邮箱 | `00 §8` / `06 §4` 只约束日志与审计 | 响应返回真实值；脱敏仅在日志 / 审计链路 | 已裁定（RISK-003） |
| 解除强制改密的入口 | `00 §2` 只规定"必须改密"，未规定如何解除 | `UserService.change_own_password`；HTTP 端点 `POST /auth/password` **已于 Phase 4 交付** | 已裁定（RISK-001 配套，已闭环） |

### Phase 2 的技术默认（延续有效）

| 位置 | 取值 | 说明 |
|---|---|---|
| `app/auth/actor.py` | `SUPER_ADMIN_ROLE_CODE = "SUPER_ADMIN"` | Spec 未冻结 SUPER_ADMIN 的标识方式；集中单点常量，冻结后只改一处 |
| `app/models/*` | 各列 `String(n)` 长度 | Spec 未规定字段长度，取常规值并与 schema 保持一致 |
| `app/db/types.py` | `VARCHAR(16) + CHECK`（`native_enum=False`） | 枚举落库形态选择；Spec 未规定 |
| `app/core/error_codes.py` | `INTERIM` 错误码 | DD-12 未冻结 |
| `app/schemas/*` | 分页字段名 `pageNum` / `pageSize`、响应体 `{list,total,pageNum,pageSize}` | 人类裁定采用，但 DD-13 仍未冻结 |

---

## 7. Phase 4 裁定（人类已裁定，2026-09-24）

> 执行 Phase：`PHASE-004-AUTH`（= `PHASES.md` Phase 3 — Authentication），
> 裁判文件 `docs/verification/003-authentication.md`。
> 人类对 `docs/DECISION-REQUEST-PHASE-4.md` 的四项草案**全部批准方案 A**。

### DD-02 Token 生命周期 —— 已冻结（方案 A）

- **令牌形态**：**不透明随机串**（`secrets.token_urlsafe(32)`，43 字符 / 256 bit），
  `sessions` 表为**唯一真源**。**不使用 JWT**。
- **TTL**：Access **15 分钟** / Refresh **7 天固定、不滑动**。
- **轮换**：每次 `POST /auth/refresh` 同时轮换 access 与 refresh；
  旧 refresh 哈希留档于 `session_refresh_token_history`。
- **复用检测（P4）**：已轮换的 refresh 再次出现 → 撤销**整个会话**
  （access + refresh 同时失效，family revocation）+ 记 `AUTH_TOKEN_REUSE_DETECTED`。
- **并发刷新（P7）**：以 `WHERE access_token_hash = 旧值 AND revoked_at IS NULL`
  做 **CAS**，保证**只有一个**请求赢得轮换；竞争失败方按**复用**处理（撤销会话）。
- **传输位置（P6）**：refresh token 放**请求体**（非 HttpOnly Cookie）。
- **口令 90 天（P8）**：过期后**允许登录**但强制改密（拒绝登录会造成"必须改密却无法登录"的死锁）。
- **为什么不需要签名密钥与 denylist**：`10 §7` 要求"Revoke 后 Token 必须不能继续访问"。
  无状态 JWT 的天然缺陷正是无法即时撤销；本方案让**每个请求**都查库并读 `revoked_at`，
  撤销一旦提交，下一个请求必然被拒 —— 不存在"TTL 内仍然可用"的窗口。
  因此 `SIGNING_SECRET` 在 Phase 4 **保留但未被使用**
  （删除一项 Frozen 要求不属于实现 Phase 可自决的范围）。
- **落地过程中的实现裁定（已在验收报告中登记）**：新 access 的到期时间
  **封顶到会话总寿命**（`SessionService.rotated_access_expiry`）。
  理由见 `docs/verification/003-authentication-result.md` DEFECT-4-01。
- **证据**：`app/core/security/token.py`、`app/models/session.py`、
  `app/services/session.py`、`app/repositories/session.py`；
  `tests/test_session_service.py`（31 例）、`tests/test_token.py`（30 例）。

### DD-03 Redis Key 命名 —— Phase 4 不使用 Redis

- 与 Phase 3 同口径：会话存于 **PostgreSQL**，不存在"两个真相"。
  因此 DD-03（Key 命名）与"Session 存储介质"均继续留 Phase 9。
- **证据**：`app/models/session.py` 模块 docstring；Phase 4 未新增任何 Redis 依赖。

### DD-11 幂等策略 —— 已冻结（方案 A：语义幂等）

- **不引入** `Idempotency-Key` 请求头。
- `POST /auth/logout` 在会话早已失效时返回 **200**
  （`{revoked: false, already_revoked: true}`）而非 401：
  登出的意图在"会话早已失效"时已经达成，返回 401 只会让客户端把一次**成功**的登出
  当成错误并重试。
- 区分"语义幂等"与"未认证"：后者仍由认证依赖返回 401。
- **证据**：`app/services/session.py:478`（`logout`）、`app/api/v1/endpoints/auth.py`；
  `tests/test_auth_api.py::TestLogoutEndpoint::test_logout_revokes_and_is_idempotent`。

### DD-01 MFA Provider —— 已冻结（方案 A：只落地边界，不选定算法）

- Phase 4 落地：登录流程中的 **MFA 检查步骤**（`04 §1` 第 6 步）、
  `MfaProvider` **Protocol**（`04 §6`）、生命周期枚举 `DISABLED/SETUP/ENABLED`、
  策略优先级 `user > role > system`（`04 §7`，user/role 两级存储留 Phase 5）。
- **不选定** TOTP / WebAuthn / SMS 中的任何一者。
- **fail-closed**：策略要求二次验证但没有可用 Provider → 抛 `ConfigurationError`，
  登录**明确失败**。宁可让配置缺失立刻可见，也不放行一个"号称有 MFA、实际没有"的系统。
  （`required=True` 且 Provider 可用时同样拒绝：挑战签发与校验属 Phase 5，
  本 Phase 不得"假装通过"。）
- **003 的判定口径**：`MFA 检查` 一项判为 PASS，标准是"步骤存在且按策略执行"。
- **证据**：`app/services/mfa.py`；`tests/test_mfa_policy.py`（13 例）、
  `tests/test_auth_service.py::TestMfaStep`（3 例）。

---

## 8. Phase 4 期间新增的 INTERIM 取值与技术默认

| 位置 | 取值 | 说明 |
|---|---|---|
| `app/core/config.py::auth_v1_prefix` | `/api/v1/auth` | **INTERIM-4-01**。认证与 `/api/v1/admin` 分开：登录是"取得身份"的入口，而 `/admin` 之下的一切都要求"已取得身份"；混挂会让后续权限守卫把登录端点也纳入拦截范围。`08 §1` 只规定了 `/api/v1/admin` 作为 Base，未禁止独立认证前缀 |
| `app/api/deps.py::get_current_actor` | 强制改密期间返回 **403**（非 401） | **INTERIM-4-02**。调用者**是**已认证的，只是当前状态下不允许访问；401 会让客户端误判"登录失效"而清掉会话，用户反而走不到改密那一步。客户端 IP 只取 socket 对端，**不读 `X-Forwarded-For`**（无可信代理列表时信任 XFF 等于允许伪造来源；属 Phase 9） |
| `app/api/v1/endpoints/auth.py` | `POST /auth/password` 为**补充端点** | **INTERIM-4-03**。`08 §3` 未列出改密端点，但 `04 §2` 冻结了"重置后首次登录必须改密"；若无解除路径，`must_change_password` 只能置 True 不能置 False —— 那不是策略，是死锁。Phase 2 已有同类先例（`POST /users/{id}/delete` 等由人类裁定补齐） |
| `app/repositories/session.py::SESSION_ACTIVITY_WRITE_INTERVAL` | `last_active_at` 写抑制窗口 **60 秒** | Spec 未规定"最近活动"的更新粒度。60 秒对应 `04 §5` 的分钟级在线判定；更细换不到可观测收益，却让每个请求都产生一次 UPDATE。**不影响任何鉴权判定** |
| `app/core/security/device.py::describe_device` | 设备粗分类形如 `Chrome · Windows · desktop` | 明确标注为**非安全信号**：仅用于展示与取证。用启发式的 UA 解析结果做安全判定会构成误判（可伪造） |
| `app/services/session.py::_UNAUTHENTICATED_MESSAGE` | 会话侧 401 文案统一为"认证失败或登录状态已失效" | `10 §5` 的落地：令牌无效 / 过期 / 已撤销 / 所属用户被禁用一律同一文案，区分它们会让攻击者能枚举"哪些令牌曾经存在" |
| `app/services/auth.py::_INVALID_CREDENTIALS_MESSAGE` | 登录失败文案统一为"用户名或密码错误" | 覆盖"用户不存在 / 口令错 / 已锁定 / 已禁用"四种内部原因；内部原因只写审计（供诊断），不对外区分 |
| `app/services/auth.py`（模块 docstring） | 自动锁定时**不**把 `status` 改为 `LOCKED` | 锁定语义完全由 `locked_until` 表达。若同时改 `status`，到期后无人把它改回（需要一个后台任务），账号会被**永久锁死**。`02 §3` 允许 `LOCKED` 存在（供管理员手工设置），与"自动锁定用 `locked_until`"不冲突 |
| `app/services/auth.py::_register_login_failure` | 达到阈值后**不清零**计数，只设 `locked_until` | "consecutive failures"要求**登录成功**才清零。若解锁时清零，攻击者只需等到锁定期结束就能立刻再获得 5 次尝试。代价（锁定期过后再错一次即再次锁定）属可接受的保守取向，已报备 |
| `app/models/session.py` | `sessions` **不含** `deleted_at` | 会话不是"可删除的业务实体"，其终态是**被撤销**（`revoked_at`）。引入软删除会出现"`revoked_at` 与 `deleted_at` 谁说了算"的第二套语义。留存 / 归档 / 分区属 Phase 6（DD-08） |
| `app/models/session.py` | **只留档 refresh 哈希，不留档 access 哈希** | Access 的 TTL 仅 15 分钟，且重放一个已轮换的 access 没有任何攻击价值（查不到即 401）。若也留档，一个 7 天会话会产出约 672 行纯噪声。这是刻意取舍，不是遗漏 |
| `app/services/session.py::rotated_access_expiry` | 轮换时新 access 的到期时间**封顶到会话总寿命** | 见 DEFECT-4-01。使 `expires_at <= refresh_expires_at` **构造性成立**，`ck_sessions_refresh_expires_not_before_access` 退化为"TTL 用反"探针 |
| `app/repositories/session.py::record_retired_refresh_token` | 用 `ON CONFLICT DO NOTHING` 写入退役哈希 | 该记录表达**集合成员关系**，重复写入语义上无意义；而在并发刷新下重复是必然的。用普通 INSERT 会让"检测到盗用却因唯一约束回滚而未能撤销会话"成为真实失败模式 |
| `app/services/mfa.py::MfaProvider` 的方法签名 | `04 §6` 的 `setup() / verify() / enable() / disable()` **补全为带参数**：`setup(*, user_id, account_name)` / `verify(*, secret, code)` / `enable(*, user_id)` / `disable(*, user_id)` | **INTERIM-4-04（补登记，2026-09-24）**。`04 §6` 是**示意性伪代码**（原文用 `例如：` 引出，且省略了全部参数），无法据此实现。补全遵循两条约束：① `setup` / `verify` 与**算法**相关 → 归 Provider，故它们只见 `secret` / `code`，**不见数据库**；② `enable` / `disable` 只改生命周期状态 → 由服务层落库，Provider 仅收 `user_id` 通知。另将 `04 §6` 未提及的 `MfaSetupMaterial`（`secret` + `provisioning_uri`）作为 `setup` 的返回类型引入。此登记为**事后补记**：该签名在 Phase 4 已实现并通过 Verification 003，但当时漏登记于本表 |

---

## 9. Phase 5 裁定（Session 管理，2026-09-24）

> 执行 Phase：`PHASE-005-SESSION-MFA` 的 **Session 部分**（= `PHASES.md` Phase 4 — Session），
> 裁判文件 `docs/verification/004-session.md`（15 项）。
> MFA 部分属 `PHASES.md` Phase 5，**未预实现**（`/auth/mfa/*` 仍不存在）。

### JUDGMENT-5-01 SUPER_ADMIN 会话保护取"任何管理员"读法（**已执行**，非自行放宽）

- **张力**：`00 §1#7` / `04 §4` 写的是"**其他**管理员不能 revoke SUPER_ADMIN"，
  而裁判 `004-session.md` 第 13 / 14 项要求"**任何**管理员不能踢 SUPER_ADMIN，
  且 SUPER_ADMIN **只能本人 logout**"。
- **取更严读法（R1）**：目标用户是 SUPER_ADMIN 时，
  **任何**管理员都不得经管理端点撤销其会话，含**另一位 SUPER_ADMIN**。
- **为什么这不是"自行决定"**：R1 同时满足冻结原文与裁判（"任何"蕴含"其他"）；
  取宽松读法（超管可互踢）会让裁判第 13 项 FAIL。
  按"不得弱化、不得把 FAIL 当 PASS"，只有 R1 可写。
- **为什么不是死洞**：被滥用 / 失陷的超管账号仍可被**禁用**
  （`SessionService.authenticate` 每请求复查 status，下一次请求即失效），
  而"不能禁用最后一个 SUPER_ADMIN"只限制最后一人的情形。
  处置手段存在，只是走"禁用账号"而不是"踢下线"。
- **实现**：新增 `AuthorizationService.assert_can_revoke_session`，
  **不修改** `assert_can_manage_user`（用户管理口径 = "非超管不得操作超管"，
  若复用它，超管互踢将被放行，裁判第 13 项 FAIL）。
- **证据**：`app/services/authorization.py`；
  `tests/test_session_management.py::TestSuperAdminProtection`（6 例）。

### FINDING-5-01 `00 §5` 的"Session 详情"未在 `08 §5` 落地为独立路由 —— 未新增接口

- **现状**：`00 §5` 要求"Session 列表/详情"；`04 §3` 列出必须记录的字段；
  但 `08 §5` 只列了 `GET /sessions` 与 `POST /sessions/{id}/revoke`，
  **没有** `GET /sessions/{id}`。
- **本次实现**："详情"由列表行的**完整字段**承载（`SessionResponse` 覆盖
  `04 §3` 的全部记录项），因此裁判 §2-§8 的逐项要求全部满足。
- **为什么不自行新增 detail 路由**：`08 §5` 是 API 契约的权威清单，
  在它之外新增路由属于扩展接口面；而裁判并未要求独立详情页。
  若产品确需"单会话详情"，请裁定后由 `08` 补齐该路由。
- **证据**：`app/schemas/session.py::SessionResponse`；
  `tests/test_session_management.py::TestSessionFields`（3 例）；
  `tests/test_session_api.py::TestResponseContract::test_user_sessions_endpoint`。

### FINDING-5-02 目标用户范围判定存在两处口径（已统一到 `allows_user`，未改旧代码）

- **现状**：`UserService._load_target`（Phase 1/2 已验收）在"非 SELF、非全局"分支
  只判 `scope.allows_department(user.department_id)`；
  而 `ResolvedScope.allows_user`（`core/scope.py` 声明的**服务端二次校验唯一入口**）
  在该分支之外还放行 `include_self` 情形（DD-19 的"SELF ∪ 其他"合并结果中的本人）。
- **差异窗口**：仅"多角色合并后 `include_self=True` 且本人部门不在部门集合内"。
  此时 `allows_user` 放行（人能看到/管理自己的会话），`_load_target` 拒绝。
- **本次实现**：会话管理统一调用 `allows_user` ——
  它是文档化的唯一入口，且 SQL 版（`scope_filters.user_scope_condition`）的语义
  与它逐分支一致；若另写一份，就会产生"SQL 一套、Python 一套"的双份真相。
- **未做的事**：**不**修改 Phase 1/2 已验收的 `UserService`。
  那是已通过 Verification 002 的代码，口径统一应由人类裁定后一次性完成
  （否则等于在未授权的范围内改动已验收行为）。
- **影响面**：差异方向是"更宽"，且只涉及**操作者本人的会话**，不涉及他人数据。
- **证据**：`app/services/session_management.py::_load_visible_user`；
  `app/core/scope.py::ResolvedScope.allows_user`；
  `tests/test_session_management.py::TestDataScope`（8 例）。

### FINDING-5-03 SUPER_ADMIN 保护只作用于 revoke（写），只读查看仍由数据范围决定

- **现状**：`004 §13/§14` 与 `00 §1#7` 的措辞都是"**踢下线** / revoke"，
  没有规定"非超管不得**查看**超管的会话"。
- **本次实现**：查看（列表 / 某用户会话）只受数据范围约束，
  不额外隐藏超管会话；revoke 才施加超管保护。
- **为什么不在读侧也排除**：扁平列表 `/sessions` 若要在读侧排除超管，
  就必须引入一条**未文档化**的 SQL 规则（对 ADMIN 角色的 NOT EXISTS 排除），
  而 `/users/{id}/sessions` 又可以定向读取 —— 两条路径会出现不一致。
  更保守的替代方案（读侧也拒绝）属**新增业务规则**，请裁定后再改。
- **风险与缓解**：全范围管理员可以看到超管会话的 IP / UA（取证元数据，非凭据）。
  若认为该元数据本身敏感，需先裁定；本实现不自行加规则，也不自行放宽 revoke 保护。
- **证据**：`app/services/session_management.py`（步骤 2 与步骤 3 的分离）；
  `tests/test_session_management.py::TestDataScope`。

### FINDING-5-04 全踢的审计 `resource_id` 为 None —— Phase 6 检索需支持 `after_data`

- **现状**：一次"踢全部"影响多条会话，`resource_id`（单值）无法表达。
  因此 `resource_id=None`，目标用户与数量记在
  `after_data = {"scope": "ALL", "target_user_id": ..., "revoked_count": ...}`。
- **单踢**仍用 `resource_type=SESSION` + `resource_id=会话 ID`。
  单踢与全踢共用同一个 `AUTH_SESSION_REVOKE` 动作（`04 §8` 只列一项
  "session revoke"），用 `after_data["scope"]` 区分。
- **待办**：若运维需要"按目标用户检索被踢记录"，Phase 6 的审计查询必须能检索
  `after_data`（DD-08 / 审计落库未冻结，本阶段不预设查询接口）。
- **证据**：`app/audit/events.py::AuditAction.AUTH_SESSION_REVOKE` 注释；
  `app/services/session_management.py::revoke_all_sessions`；
  `tests/test_session_management.py::TestRevokeAll::test_revoke_all_audited_with_count`。

---

## 10. Phase 5 期间新增的 INTERIM 取值与技术默认

| 位置 | 取值 | 说明 |
|---|---|---|
| `app/repositories/session.py::online_session_condition` | 在线 = **未撤销 + 会话总寿命（refresh）未过 + 用户 ACTIVE 且未删除** | **INTERIM-5-01**。`04 §5` 只说"由有效 Session / 最近活动**等**规则计算"，未给口径。**不把 access 到期算作离线**（access 仅 15 分钟，客户端 refresh 即可续用，会话并未结束）；**不引入空闲阈值**（Spec 未规定数值，自造数值等于发明业务规则），需要按空闲判断时读 `last_active_at` |
| `app/schemas/session.py::SessionListQuery.online` | `online=true` 只返回在线会话；`false`（默认）= **不筛选** | **INTERIM-5-02**。`04 §5` 要求"后台在线用户查询"，而 `08 §5` 只列了 `GET /sessions` 一条路径，故以查询参数实现，**未新增**"在线用户"专用端点。默认不筛选是因为排查"某个登录为什么失效"恰恰需要看到**已结束**的会话 |
| `app/schemas/session.py::SessionResponse.online` | 响应中**暴露**在线判定结果 | **INTERIM-5-02（配套）**。若只在查询参数上过滤而不返回判定结果，调用方只能自行重实现一遍规则，必然产生第二份真相 |
| `app/api/v1/endpoints/sessions.py` | `/users/{id}/sessions*` 与 `/sessions*` **实现同处一个模块** | **INTERIM-5-03**。路径前缀属 Users 资源（`08 §4`），但业务语义是会话管理：共用同一 Service、同一数据范围、同一超管保护。拆开会让同一条安全规则写在两个文件里 |
| `app/services/authorization.py::ApiPermissionCode.SESSION_MANAGE` | 查看与踢下线**共用**一个 API 权限位 | **INTERIM-5-04**。两者面向同一类主体；拆细属权限资源治理（`03`），Spec 未给出会话相关资源编码表。真正的越权防护由数据范围与超管保护承担。权限位命名规范本身待 DD 冻结 |
| `app/repositories/session.py::list_for_admin` | 排序 `login_at DESC, id DESC` | **INTERIM-5-05**。`login_at` 是 `04 §3` 的字段；`id`（Snowflake 单调）作为同秒并列的第二排序键 —— 没有第二键时分页会在并列数据上重复 / 漏行 |
| `app/repositories/session.py::list_active_for_user` | 全踢只撤销**当前有效**的会话 | **INTERIM-5-06**。给早已自然过期的会话补写 `ADMIN_REVOKE` 会让审计无法区分"到期结束"与"被人踢掉"——那是**改写历史**，取证价值高于"计数好看" |
| `app/repositories/session.py::revoke_and_retire` | 会话终结（置撤销 + 留档 refresh 哈希）**全系统唯一实现** | 本人登出 / 单踢 / 全踢三类调用方共用。若各自实现，会出现"登出退役了哈希、踢下线没有"的不一致，使取证线索取决于用户是"自己退出"还是"被踢" |
| `app/services/audit_guard.py`（复用） | 越权 / 超管保护的拒绝一律写 FAILURE 审计 | `10 §8`。拒绝路径包在 `denial_audited` 守卫内，避免因提前 `raise` 而绕过审计（Phase 2 已验证过的模式） |
| `app/audit/events.py::AuditAction.SESSION_READ` | 会话**读取**也记审计 | `04 §8` 未把"查看会话"列为安全事件，但会话元数据含 IP / UA，属敏感读取面；与既有 `USER_READ` 同口径记录，使"谁在踢之前查过这个账号"可回答 |

---

## 11. Phase 5 MFA —— 阻塞与新增未冻结项（2026-09-24）

> 执行 Phase：`PHASES.md` **Phase 5 — MFA**，裁判文件 `docs/verification/005-mfa.md`（13 项）。
> **状态：`BLOCKED — NEED USER DECISION`，在编码前停止。**
> 正式决策请求：`docs/DECISION-REQUEST-PHASE-5.md`。
> 本节仅登记结论，不构成任何冻结。

### 11.1 为什么必须在编码前停止

`07 §7` 用一句"**具体字段随 Provider 设计确定**"把**持久化模型**绑在
**尚未冻结的 Provider 选型**上；`16 §技术设计待冻结项 #1` 又规定
"这些属于技术设计决策，应在实现相应 Phase 前冻结"——现在正是该 Phase。
四个未冻结决策**互相耦合**（密文格式决定列类型、Provider 选型决定 `secret` 形态、
挑战机制决定登录响应契约、策略模型决定迁移脚本），
不存在"先做一半"的安全切分，强行切分必然返工。

### 11.2 新增未冻结项

#### DD-22 MFA Secret 加密方案 —— 未冻结（阻塞 Phase 5）

- **Spec 只冻结了义务**（`04 §6`「Secret 必须加密保存」、`13 §2` 密钥由环境变量 /
  Secret Management 注入、`10 §4` / `06 §4`「MFA Secret 绝不记录」），
  **未冻结**算法、密文格式、密钥长度、nonce 策略、是否绑定 AAD、密钥轮换。
- **现状缺口（可复现）**：`app/core/config.py::_guard_production_secrets`
  在 `APP_ENV=prod` 时检查 `POSTGRES_PASSWORD` / `REDIS_PASSWORD` /
  `SIGNING_SECRET` / `ENCRYPTION_KEY`，**未包含 `MFA_ENCRYPTION_KEY`**；
  而 `app/core/security/` 下**不存在任何加解密设施**。
- **草案 A**：AES-256-GCM；密钥 = `MFA_ENCRYPTION_KEY`（base64 的 32 字节）；
  密文 = `v1.<base64url(nonce‖ct‖tag)>`；AAD 绑定 `user_id` + `provider`；
  密钥缺失 / 解密失败一律 fail-closed；密文列用 `Text`。
- **关键理由**：AAD 绑定是为了防"跨行替换"——没有 AAD 时，
  把 A 的密文写进 B 的行会让系统**用 A 的 secret 正常验证 B 的登录**且无迹可循。
  版本前缀是为了将来能逐行渐进迁移，而不是停机全量重加密。

#### DD-23 MFA 挑战与会话续接机制 —— 未冻结（阻塞 Phase 5）

- **张力**：`04 §1` 的顺序图把 `create session` 放在 `MFA check` **之后**，
  但 `08 §3` 要求存在 `POST /auth/mfa/verify` ——
  "密码已通过、MFA 未完成"的中间态**必须有载体**，而这个载体无 Spec 依据。
- **草案 A（推荐）**：该中间态**不建 Session**。
  `POST /auth/login` 返回一次性 `mfa_token`（5 分钟、只存哈希、成功或失败即作废）；
  `POST /auth/mfa/verify` 校验通过后才建 Session 并签发令牌。
- **为什么不能提前建 Session**：Phase 4 已验收的在线判定
  （`online_session_condition`：未撤销 + 未过期 + 用户 ACTIVE）会把
  "**只输对密码的人**"立刻算成**在线**；更要紧的是"认证是否完成"
  会退化成 `sessions` 上的一个**可选列**——任何一条漏检该列的路径
  都是**认证绕过**。把安全状态放在"默认放行"的位置不可接受。
- **草案 A 附带**：MFA 挑战失败**不锁定账号**（`10 §5` 的锁定语义是"密码连续失败"）。
  否则"密码正确但拿不到动态码"（如手机丢失）的用户会被锁在账号外，
  而正确处置应是走恢复流程。防暴力由**挑战级作废 + rate limit**承担。

#### DD-24 MFA 策略与凭据的存储模型 —— 未冻结（阻塞 Phase 5）

- **未冻结**：`07 §7` 建议的 `user_mfa` 字段（`provider` / `status` /
  `encrypted_secret` / `setup_at` / `enabled_at` / `verified_at`）**全是凭据字段**，
  **没有任何一处**表达 `04 §7` 要求的"是否要求 MFA"；
  且该节明写"**建议**包含"与"具体字段随 Provider 设计确定"。
- **草案 A**：**策略与凭据分离**——
  `mfa_policies(subject_type, subject_id, required)`（`subject_type ∈ {USER, ROLE}`，
  `required = NULL` 表示**未表态**，唯一约束 `(subject_type, subject_id)`）
  + `user_mfa(user_id, provider, status, encrypted_secret, *_at)`（唯一键 `(user_id, provider)`）
  + `mfa_challenges`。
- **`required` 必须可空**：这与 Phase 4 已固化的语义**逐字对齐**——
  `UnsetUserMfaPolicySource` / `UnsetRoleMfaPolicySource` 返回 `None`（未表态，
  继续向下询问）；若把"未表态"合并成 `False`，**用户级实现一旦上线就会永久屏蔽
  角色级策略**，且运行时完全看不出来（`app/services/mfa.py` 已将此理由写入 docstring）。
- **唯一键取 `(user_id, provider)` 而非仅 `user_id`**：支持同一用户未来从 TOTP
  **迁移**到 WebAuthn 时两者并存，由 `MfaProviderRegistry.active_name` 决定生效者
  （`04 §6` 抽象中的 `MfaProvider.name` 已为该用途预留）。
- **跨 Phase 边界（需裁定）**：`05 §5` 把 "MFA default policy" 列为**系统参数**
  （须有类型 / 默认值 / 状态 / 描述 / 审计），而系统参数属 **Phase 7**；
  现状由环境变量 `settings.mfa_required_default` 提供（需重启才生效、无审计）。
  候选：Phase 5 保持环境变量、**Phase 7 迁入参数表**（推荐，`MfaPolicyResolver`
  已把 system 级抽象为构造参数，迁移时**无需改动 MFA 代码**）；
  或 Phase 5 就地建参数表（会与 Phase 7 交付**重叠**、可能形成两套参数机制）。

### 11.3 裁判第 12 项「恢复流程不会泄漏 Secret」—— 无 Spec 依据

- **可复现证据**：

  ```text
  grep -rn "恢复流程\|恢复码\|备用码\|recovery code\|backup code" docs/
    → docs/verification/005-mfa.md:14（**仅裁判书自身那一行**）
  grep -rn "恢复\|recovery\|Recovery" docs/spec/
    → （无输出）
  ```

- **结论**：Spec 未定义 MFA 的"恢复流程"，也未规定其中 Secret 的处理方式，
  但裁判项要求验证它。三种可能意图（恢复码 / 管理员重置 MFA / 仅"重置与查询过程中
  Secret 不回显"）的实现差异极大，其中前两者属**新增业务能力**
  （会超出 `08 §3` 的端点清单），按 `AGENTS.md §4` 必须**先停止扩展、记录问题**。
- **处置**：按 **BLOCKED_BY_DESIGN** 记录（不是环境阻塞，而是"**验收标准缺少
  Spec 依据**"），**不判 PASS、不判 FAIL**，等待人类澄清。

### 11.4 本 Phase **未**写入任何 MFA 业务代码

`git status` 干净；`app/` 下无 MFA 模型、无加解密模块、无 `/auth/mfa*` 端点。
已冻结且已在 **Phase 4** 交付的部分（`MfaProvider` 抽象、`MfaStatus` 枚举、
`MfaPolicyResolver`、脱敏规则、`AuditAction.MFA_*` 枚举）**未被改动**。

> ⚠️ 以下 §12 记录的是**同一 Phase 的后续执行**：在人类下达
> "不要询问我，完成所有任务"之后，Agent 依据 §11 已写明的**草案 A**
> 继续落地。§11 的阻塞登记**保留**（不改写历史），§12 记录实际采用的选项
> 与其中的每一处取舍。

---

## 12. Phase 5 MFA —— 实际落地口径（2026-09-24 / 2026-09-25）

> 执行依据：人类指令"不要询问我，完成所有任务"。
> 原则：**只在草案 A 中挑选不与 Frozen Spec 冲突的选项**；
> 任何需要"发明业务能力"的选项一律**不做**，登记为待裁定。

### 12.1 采用与未采用的选项

| 未冻结项 | 采用 | 未采用 | 未采用的理由 |
|---|---|---|---|
| **DD-01** Provider 选型 | **不选定产品级 Provider**；`app/` 内零算法实现；测试专用 Provider 只放 `tests/`；无 Provider 时 fail-closed | 正式冻结 TOTP / Email / SMS | `00 §4`、`16 §1`、`PHASES.md` Phase 5、`PHASE-005-SESSION-MFA.md` **四处**禁止实现者宣布具体 Provider 为需求事实。这条比"把功能做全"更硬 |
| **DD-22** Secret 加密 | AES-256-GCM；密钥 `MFA_ENCRYPTION_KEY`（base64 的 32 字节）；密文 `v1.<base64url(nonce‖ct‖tag)>`；**AAD 绑定 `user_id:provider`**；密钥缺失/格式错/解密失败一律 fail-closed；密文列用 `Text` | 密钥轮换、多密钥并存 | 属 DD-09 Secret Manager 范畴（未冻结）。版本前缀已为**将来**加轮换预留为纯增量改动 |
| **DD-23** 挑战与会话续接 | **不建 Session**；`POST /auth/login` 回一次性 `mfa_token`（TTL 300s、库内只存 SHA-256、成功或达上限即核销）；`POST /auth/mfa/verify` 成功后才建 Session 并签发令牌 | 提前建 Session 并标记 pending | Phase 4 已验收的在线判定会把"只输对密码的人"算成**在线**；且"认证是否完成"会退化成 `sessions` 上的**可选列**，漏检一处即**认证绕过** |
| **DD-24** 存储模型 | **策略与凭据分表**：`mfa_policies` / `user_mfa` / `mfa_challenges`；`required` **可空**；`user_mfa` 唯一键 `(user_id, provider)` | 把 `required` 并进 `user_mfa` | 角色级策略不属于任何用户，在 `user_mfa` 里无处安放；强行合并只能放弃 `04 §7` 的角色级策略 |
| **system 级默认值归属** | **保持环境变量** `MFA_REQUIRED_DEFAULT`，**Phase 7** 迁入系统参数表 | Phase 5 就地建参数表 | `05 §5` 把 "MFA default policy" 列为**系统参数**（含类型/默认值/状态/描述/审计），而系统参数整体属 **Phase 7**；Phase 5 建表会与 Phase 7 交付重叠并形成两套参数机制。`MfaPolicyResolver` 已把 system 级抽象为构造参数，迁移时**无需改动 MFA 代码** |
| **裁判第 12 项**"恢复流程" | 取 **(c)** 读法：**不新增**恢复码 / 管理员重置；以自动化护栏钉住"Secret 只在 setup 出现一次" | 恢复码 / 管理员重置 MFA 端点 | 两者都要求新增表与端点（超出 `08 §3` 清单），属**新增业务能力**；`AGENTS.md §4` 禁止自行扩范围。已在 `DECISION-REQUEST-PHASE-5.md` §5 请求澄清，**尚未收到** |

**未新增第三方依赖**：加解密用 `cryptography`（其本身是 `asyncpg` 之外的成熟库，
已在 `pyproject.toml` 锁版 `46.0.3`）；TOTP 类库（`pyotp` 等）**一个都不装** ——
装了就等于选定了 Provider。测试用例中含 AST 级护栏，
扫描 `app/**/*.py` 的 import，禁止 `pyotp` / `onetimepass` / `fido2` / `webauthn`
/ `yubico_client` / `twilio` / `qrcode` 出现在产品代码里，也禁止 `app/` 下出现
以 `totp` / `hotp` / `webauthn` / `fido` / `sms` 命名的模块。

### 12.2 JUDGMENT-MFA-01 策略要求但用户尚未绑定 → **放行登录**并标记

- **情形**：策略要求二次验证，但该用户**尚未完成绑定**（无 `ENABLED` 凭据）。
- **处置**：**不阻断登录**，在 `LoginResult.mfa_setup_required` 中如实标记，
  由客户端引导用户去绑定。
- **为什么不能阻断**：绑定接口 `POST /auth/mfa/setup` 需要一个**已认证会话**。
  若在登录处拒绝，"没绑定"就永远走不到"绑定"——那是**死锁**，不是安全。
  对照：`10 §5` 的强制改密之所以能阻断，是因为存在 `get_current_actor_allow_password_change`
  这条**替代路径**；MFA 绑定没有等价路径。
- **不构成弱化**：放行的是"**登录**"，不是"**免二次验证**"。
  一旦用户完成绑定，下一次登录立即被要求二次验证（有端到端用例）。
  这一点与 `04 §7` 的策略意图一致 —— 策略要求的是"该用户必须有 MFA"，
  而新用户需要一个受控的窗口去完成绑定。

### 12.3 FINDING-MFA 挑战签发不产生独立审计事件

- `04 §8` 的安全日志清单只有 **MFA setup / enable / disable / failure** 四类，
  没有"挑战签发"。新增一个动作属于**扩展 Spec**，故本 Phase **保持沉默**。
- 留痕并未缺失：真正需要追溯的是随后可能发生的 `MFA_FAILURE`
  （含 `WRONG_CODE_ON_LOGIN`）与成功核销时的 `AUTH_LOGIN_SUCCESS`
  （`after_data.via = "MFA_CHALLENGE"`）。
- 已登记，等待裁定是否补这个事件。

### 12.4 Phase 5 新增的 INTERIM 取值与技术默认

| 位置 | 取值 | 说明 |
|---|---|---|
| `app/services/mfa_management.py::CHALLENGE_TTL_SECONDS` | **300 秒** | **INTERIM-5-07**。草案未给 TTL；300 秒足以完成"打开 App → 输码"，又不至于把一次性凭证的暴露窗口拉长到"跨会话复用"的程度 |
| `app/services/mfa_management.py::MAX_CHALLENGE_ATTEMPTS` | **5 次后作废挑战** | **INTERIM-5-08**。草案 Q3 写"成功或失败即作废"、Q4 又写"5 次后作废"，**两者并存时 Q4 无意义**。取 Q4：Q3 想解决的是"用同一挑战**无限次**试码"，有限次上限已达成同一目的；而一次性作废会让偶发输错变成必须重走登录。这是对草案**内部不一致**的解释，不是新要求 |
| `app/repositories/mfa.py::get_role_policy_required` | 多角色合并取 **OR**（任一要求 ⇒ 要求） | **INTERIM-5-09**。`04 §7` 只规定**层级间**优先级，未规定**同层内**多角色如何合并。取 AND 或"宽松者胜"会让同时持有高敏角色与宽松角色的用户**静默地**失去二次验证 —— 未经授权的安全弱化，只有 OR 可写 |
| `app/models/mfa.py::MfaChallenge.token_hash` | 挑战令牌库内**只存 SHA-256** | 与 access / refresh 同口径（`app/core/security/token.py::hash_token`）。DB 泄漏时攻击者无法用哈希续完任何一次登录 |
| `app/models/mfa.py::MfaPolicy.subject_id` | **无数据库外键**（泛化主体） | 引用完整性由服务层校验。代价明确记录：这不是"省略校验"，而是把校验放在**知道主体类型**的地方；两个可空外键会让"每主体至多一条策略"无法用单个唯一约束表达 |
| `app/models/mfa.py::UserMfa` | **不设 `deleted_at`** | 凭据终态由 `status = DISABLED` 表达（生命周期的起点也是终点）。再引入软删除会产生"`status` 与 `deleted_at` 谁说了算"的第二套语义 |
| `app/services/mfa.py::MfaService.check_login` | 要求 + Provider 可用 → **返回 `required=True`**（不再抛"尚未实现"） | **INTERIM-5-10**。Phase 4 的占位分支（当时 `/auth/mfa/verify` 不存在）随真实实现到位而删除，属"占位实现退场"，**不是验收标准放宽** —— "要求但**无** Provider"的 fail-closed 分支一字未改（有专门用例钉住） |
| `app/core/security/aead.py::build_secret_box` | 构造失败抛 `SecretBoxError` → 服务层映射为 `ConfigurationError` | `SecretBoxError` **刻意不继承** `AppError`：加密层的失败不应直接映射为 HTTP 响应，语义由调用方（MFA 服务）决定。有专门用例断言这一继承关系 |
| `tests/conftest.py` | 注入测试专用的 `MFA_ENCRYPTION_KEY` | `.env.example` 刻意把它留空（真实部署由环境/密钥管理注入，`13 §2`）。若测试沿用空值，**所有涉及 Secret 的验收项都无法被验证**——那会让裁判第 3 项永远无法判定 |
| `app/core/config.py::_guard_production_secrets` | 补上 `MFA_ENCRYPTION_KEY` 的 prod 校验 | **修复 §11.2 记录的真实缺口**：此前 `prod` 只校验 4 个密钥，唯独漏了 MFA 加密密钥 —— 意味着生产可以用空密钥启动，直到第一次绑定才失败 |

---

## 13. Phase 6 日志 / 审计 / Trace —— 实际落地口径（2026-09-25）

> 执行依据：人类指令"继续执行不再问我完成整个项目"。
> 裁判：`docs/verification/006-logging-audit.md`（5 类日志 / 4 项 Trace /
> 16 项 Audit / 5 项 Masking / 5 项 Retention）。

### 13.1 DD-08 仍未冻结 → 不分区，交付"表 + 清理能力"

`16 §技术设计待冻结项` 的 **DD-08**（PostgreSQL 声明式分区 / pg_partman /
归档到对象存储）**至今未裁定**。因此本 Phase：

- **不分区**，只建普通表 + 索引；
- 交付保留期清理能力（`LogRetentionService` + `scripts/purge_logs.py`）。

依据是 `06 §5` 的原文 —— "**必须提供后续**归档/清理能力"，以及
`07 §8` 的"高容量日志应**考虑**分区与 retention job"（"考虑"不等于"必须分区"）。
**JUDGMENT-6-01**：分区化不改列、不改查询，将来按 DD-08 落地时是**纯增量**改动，
因此现在的延期不会产生返工，也不会让现有的清理能力失效。

### 13.2 三类日志是**同一批事件的三切片**，不是三套写入点

`06 §1` 把日志分为五类，`06 §2` 只规定了 Audit 的 15 个字段。
本 Phase 的口径：

```text
一条审计事件 ─┬─→ audit_logs      （全部事件，2 年）
               ├─→ security_logs   （安全类，180 天）
               └─→ operation_logs  （业务类，180 天）
```

因此 `security_logs` / `operation_logs` 是**切片**，不是第二个记录入口。
否则"同一次登录失败"会有两条互相独立、可能不一致的写入路径。

### 13.3 Phase 6 新增的 INTERIM 取值与技术默认

| 位置 | 取值 | 说明 |
|---|---|---|
| `app/models/logs.py` 表名 | `application_logs` | **INTERIM-6-01**。`07 §8` 写的是 "application logs"（其余四张写了 `_logs` 后缀）。此处统一加后缀，否则 ORM 模型名与表名不成对应，且与其余四张表的命名规则不一致 |
| `app/audit/classify.py` | 三个封闭集合覆盖全部 `AuditAction` | **INTERIM-6-02**。Spec 未枚举"动作 → 类别"。有测试断言 `SECURITY ∪ OPERATION ∪ READ_ONLY == set(AuditAction)`，因此"新增动作忘了分类"会在 CI 立刻失败，而不是**静默地**只进审计表 |
| `app/repositories/logs.py::_clamp` | 超长值截断到列宽并追加 `…` | **INTERIM-6-03**。`varchar(n)` 超长会**报错**，而报错发生在落库的独立事务里 → **整批日志一起丢失**。于是"发一个 64KB 的 UA"就是一条让审计静默消失的通道。截断只损失尾部，不截断损失全部 |
| `app/core/logging.py::DB_LOG_LEVEL` | `INFO` | **INTERIM-6-04**。`06 §1` 的 Application Log 是面向运维的"应用运行日志"，不是开发态诊断。若跟随 `DEBUG`，几条调试语句即可在 30 天内写入千万行，淹没真实事件 |
| `app/services/log_retention.py::RETENTION_DAYS["audit"]` | **730 天** | **INTERIM-6-05**。`06 §1` 写 "2 years"，未规定按日历年（闰年 730/731）还是 365×2。取 730 使边界不依赖"当前处于哪个日历区间"，从而可被测试精确断言；差异最多 1 天且方向不确定 |
| `app/audit/buffer.py` 落库位置 | 中间件的**最后一个响应分片**之前，独立事务 | **INTERIM-6-06**。锚在"函数返回后"会留下窗口：客户端拿到 200，进程随即崩溃，而这次操作的审计尚未落库 —— 最需要留证的恰是那一刻。代价是每请求一次额外数据库往返。`finally` 保留兜底调用（空缓冲不建连接） |
| `scripts/purge_logs.py` | 提供入口但**不内建调度器** | **INTERIM-6-07**。是否在进程内跑定时任务取决于部署形态（单实例/多实例/K8s CronJob）。内建调度会在多实例下变成"N 个实例各清一遍" |
| `app/audit/buffer.py` 熔断参数 | 超时 **5s** / 连续失败 **3** 次打开 / 冷却 **60s** | **INTERIM-6-08**。asyncpg 的连接超时默认 **60 秒**：数据库主机"丢包"时一次落库就能挂住请求 60 秒，而 `/health` 是**存活探针** —— 挂住它会让编排系统重启进程，把"数据库抖动"放大成"服务不可用"。熔断期内的日志被**丢弃**并计入 `dropped_logs`（可观测，不是静默丢失） |
| `app/core/masking.py::scrub_text` | 自由文本中的令牌**整体**替换为 `<redacted>` | **INTERIM-6-09**。`06 §4` 对 token 的规则是"保留前 6 个字符"，那是**具名 token 字段**的展示口径；`10 §4` 的措辞是"不得记录 access token **plaintext**"。自由文本没有"这是个 token 字段"的上下文，故取更严者。方向只允许更严 |
| `app/models/logs.py::SecurityLog.reason` | 从 `after_data["reason"]` 提升为独立列 | **INTERIM-6-10**。Spec 未定义 `security_logs` 的字段。该值本就存在（`auth_audit` 写入 `after_data` 以遵守"审计 15 字段不可增删"），提升为列只是让"按 `LOCKED` / `TOKEN_REUSE_DETECTED` 检索"不必反解 JSONB |
| `app/middleware/trace.py` | `access_logs.path` **不含 query string** | **INTERIM-6-11**。查询串里常出现 `?token=` / `?code=` 这类一次性凭据，写进保留 30 天的访问日志等于给凭据开一条长期留存通道 |
| `app/core/context.py::_actor_id_var` | `operator_id` 经 ContextVar 从认证依赖传到中间件 | **INTERIM-6-12**。中间件**不解析令牌** —— 重复解析等于把认证逻辑变成两份实现，而"哪一份说了算"没有答案。该机制成立的前提是**纯 ASGI 中间件**（`BaseHTTPMiddleware` 会各自持有上下文副本，`operator_id` 将永远是 NULL，并有专门用例钉住） |
| `app/models/logs.py::LOG_MODELS` | 以**表名**为键的单一清单 | **INTERIM-6-13**。避免"有哪些日志表"在迁移、保留期服务、测试里各写一份而漂移；有测试断言 `set(LOG_MODELS) == set(RETENTION_DAYS)`，即"新增日志表却忘了定保留期"会立刻失败 |

### 13.4 FINDING-6-01 分类失败时**先写审计主表**

`classify()` 对未分类动作抛 `KeyError`（刻意不静默回落）。
但调用点若让异常冒到 `flush_logs()`，代价是**同批次所有日志一起丢失** ——
其中包含本该留痕的审计主记录。

因此 `LogRepository._classify_safe` 把异常收窄为"这一条的**切片**不写"：
`audit_logs` 照写（取证不丢），并记 ERROR。这不属于静默回落 ——
静默回落指"照样写进某个类别且无人知晓"，这里的缺口是响亮的，且有专门用例。

### 13.5 Phase 6 关闭的历史缺口

Phase 2~5 期间，`app/api/deps.py` 里的服务全部用默认的 `NullAuditRecorder`
构造，即**所有审计事件止步于内存**（只有测试替身看得见）。本 Phase：

| 缺口 | 关闭方式 |
|---|---|
| 业务审计事件从未落库 | `deps.py` 的四个服务工厂统一注入 `BufferingAuditRecorder` |
| 令牌无效 / 会话已撤销 / 用户不可用 / **Refresh Token 复用**（DD-02 family revocation）在审计中不可见 | `get_session_service` 同步注入 —— 它是**每个受保护端点**的必经之路，此前这条路径上的事件全部丢失 |
| 消息正文（`msg` / `args`）从未脱敏 | `MaskingFilter` 重写 `record.msg` 并清空 `args`；两个 formatter 覆盖 `formatException` |
| `before_data` / `after_data` 在写入前未脱敏 | `LogBuffer.add_audit` 在**入缓冲时**即递归脱敏（JSONB 无法事后补救，且未脱敏数据在内存中停留最短） |

### 13.6 FINDING-6-02 包 `__init__` 重导出遮蔽同名子模块（已修复）

**现象**：完整测试运行出现 2 个 FAIL，错误信息都是

```text
AttributeError: 'function' object at app.audit.classify has no attribute 'SECURITY_ACTIONS'
```

**根因**：`app/audit/__init__.py` 重导出了 `classify` **函数**。
`classify` 同时是子模块名（`app.audit.classify`）与其中的函数名；
重导出把包上的 `classify` 属性从"模块"覆盖成"函数"，
于是所有按**点号字符串**定位目标的工具（`pytest` 的
`monkeypatch.setattr("app.audit.classify.X", ...)`、`mock.patch`）解析失败。

**为什么它难发现**：`sys.modules["app.audit.classify"]` 仍然是模块，
`import app.audit.classify` / `importlib.import_module(...)` 一切正常；
只有 `getattr(app.audit, "classify")` 这条路径拿到的是函数。
即"按模块导入"的代码完全正常，"按字符串定位"的代码全部失效 ——
两者在同一进程里并存，却不是同一个东西。

**修复**：

1. 包 `__init__` 不再重导出 `classify`（保留 `LogCategory` 与三个动作集合，
   它们不与子模块同名），并在模块文档写明原因；
2. 新增 `TestPackageNamespaceDoesNotShadowSubmodules`（含一条真实复现失败
   用法的用例），把"点号路径只有一个含义"钉成回归测试。

**通用规则（本 Phase 起适用）**：包的 `__init__` **不得**重导出与子模块同名的名字。
代价只是多写一次完整导入路径。

> 修复过程记录在 `docs/verification/006-logging-audit-result.md §5.1`
> （FAIL → 定位根因 → 修复 → 重新测试 → 重新执行完整 Verification）。


---

## 14. Phase 7 字典 / 系统参数 —— 实际落地口径（2026-09-25）

> 执行依据：人类指令"继续执行不再问我完成整个项目"。
> 裁判：`docs/verification/007-dictionary.md`（字典类型 5 项 / 字典项 9 项 / 规则 4 项）。
> 执行计划：`PHASES.md` **Phase 7 — Dictionary / System Parameter**。

Phase 7 与 Phase 1~6 的区别：**本次 Spec 明确缺了两样东西** ——
系统参数的表名与端点路径（`05 §5` 只有一句"必须有类型/默认值/状态/描述和审计"，
`08 §9` 的 Endpoint 清单里也只有 Dictionary）。因此本 Phase 的登记项
集中在"把 Spec 未写的部分补成最小推导，并说明改动面"。

### 14.1 Phase 7 新增的 INTERIM 取值与技术默认

| 位置 | 取值 | 说明 |
|---|---|---|
| `app/models/param.py::SysParam.__tablename__` | `sys_params` | **INTERIM-7-01**。`05 §5` 未给表名，而同一份 Spec 的 §2 把字典表命名为 `sys_dict_type` / `sys_dict_item`。取同一前缀是最小推导。改动面：一次 migration + 一处 `__tablename__` |
| `app/services/system_param.py::_resolve` | `status=DISABLED` → `ConfigurationError` | **INTERIM-7-02**（`app/models/enums.py` 中的注释亦标记为 JUDGMENT-7-02，同一条取舍）。`05 §5` 要求参数"必须有状态"，但未定义状态语义。两种宽容读法都会制造**静默的安全降级**："停用⇒按默认值生效"让治理字段失效；"停用⇒当作未配置"让"有人故意关掉 MFA 要求"与"没人配过这个参数"不可区分。故只有 fail-closed |
| `app/models/dict.py` 的 partial unique index | `uq_sys_dict_item_type_default_active` | **INTERIM-7-03**。Spec 要求有 `is_default` 字段但未规定"几个默认项"。服务层取"后者胜"（可预期），数据库用 partial unique index 兜底（"服务层不是唯一写入路径"）。若人类裁定允许多默认项，改动面只是一条索引 |
| `app/api/v1/endpoints/params.py` + `app/core/config.py::public_v1_prefix` | `/api/v1/admin/params`（GET/POST/GET id/PUT/DELETE） | **INTERIM-7-04**。`08 §9` 没有系统参数端点，而 `05 §5` 要求"审计"——没有可调用接口就只能直接改库，落不进审计。路径按 `08 §1` 的 admin Base + 与 `/dicts` 对称的资源名推导。附带新增 `settings.public_v1_prefix`（`/api/v1`）：公开字典查询**不在** admin 域，需要一个与 `api_v1_prefix`（`/api/v1/admin`）并列的前缀，而不是字符串拼接 |
| `app/services/dict.py::get_public` | 公开查询**不写审计** | **INTERIM-7-05**。它是每个登录用户每次加载页面都会调的读操作，逐次审计会把审计表变成访问日志并稀释 FAILURE 信号。管理侧读（`/admin/dicts*`）仍逐次审计 —— 两者口径不同是有意的（`06 §1` 的审计对象是"高价值业务变更与管理员行为"） |
| `app/audit/classify.py` | `PARAM_CREATE/UPDATE/DELETE` → `SECURITY_ACTIONS` | **INTERIM-7-06**。Spec 未枚举"动作 → 类别"。系统参数承载的正是运行时安全策略（本 Phase 落地的 `mfa.required_default` 就是 MFA 的策略最低层），因此其变更按安全日志留存 |
| `app/services/dict.py::delete_item` | 允许删除默认项 | **INTERIM-7-07**。Spec 未规定该场景。禁止删除会要求"先把默认项挪走"，让管理员卡在中间状态；允许删除的后果只是"该字典暂时没有默认项"，调用方可自行决定兜底 |
| `app/services/system_param.py::_param_snapshot` | 审计**不记录参数值** | **INTERIM-7-08**。参数可能承载密钥类配置（`13 §2` 只说"不得硬编码"，参数表是自然落点），而脱敏规则按**键名**匹配，`param_value` 不在其中；审计表 append-only 且保留 2 年 —— 写进去就是一条**不可撤回的泄漏通道**。只记 `value_is_set` / `value_length` / `effective_source`，代价（答不出"改前是什么值"）明确登记 |
| `app/services/system_param.py::_assert_key_format` | `param_key` 不允许空白字符 | **INTERIM-7-09**。Spec 未规定键格式。含空格的键在配置面板里肉眼不可分辨，而"键写错"的表现是读取方**静默走 fallback** —— 最难发现的故障 |
| `app/services/system_param.py::update_param` | `param_key` / `param_type` 不可修改 | **INTERIM-7-10**。与 `dict_code`/`role_code` 同口径；且类型是参数与读取代码的契约，允许改类型会把不一致**推迟到读取时**才暴露（那通常正是登录路径）。落在端口形状上（DTO `extra="forbid"` + Service 无该形参），有测试钉住 |
| `app/api/v1/endpoints/dicts.py::get_public` | 必须**已认证**，不要求 `DICT_MANAGE` | **JUDGMENT-7-03**。Spec 称其为"公开查询"且刻意不放在 `/admin` 下，但**没有一句**说它无需认证。不采用匿名读法的理由：Spec 未授权匿名访问，而"把数据端点设为匿名"是**安全面的扩张**；反向（已认证即可读）不构成对需求的削弱。改动面只有一处依赖（`get_current_actor`） |

> 上表按代码内注释的编号原样登记；编号不连续处保持原样，以便与代码注释**一一对应**。

### 14.2 FINDING-7-01 登录路径此前不使用仓储级 MFA 策略解析器（已修复）

**现象**：Phase 5 的 `AuthService.__init__` 用 `MfaService(resolver=None)`，
即 `MfaPolicyResolver` 的默认构造 —— 其 user / role 两层是
`UnsetUserMfaPolicySource` / `UnsetRoleMfaPolicySource`（**永远返回"未表态"**）。

**后果**：登录时"角色级策略要求 MFA"**不会生效**，会直接落到 system 层；
更关键的是，Phase 5 的 fail-closed 分支（"策略要求但无可用 Provider"）
在这条路径上**永远不会触发** —— 一个配了角色级 MFA 要求的系统可以正常登录。

**为什么直到 Phase 7 才暴露**：Phase 5 的测试全部直接构造 `MfaService` /
`MfaManagementService` 并注入自己的 resolver，**没有一条用例走
`get_auth_service` 这条依赖装配路径**。Phase 7 因为要把 system 层默认值
从环境变量换成参数表，第一次真正读了这个工厂函数，才看见它构造的是默认解析器。

**修复**：`AuthService` 与 `MfaManagementService` 统一经
`build_policy_resolver(MfaRepository(session), RoleRepository(session), system_default=...)`
装配；`system_default` 由依赖层 `await resolve_mfa_required_default(session)` 解析
（`MfaPolicyResolver` 的 `system_default` 是**构造期入参**，解析需要 IO，
而构造是同步的，因此必须在异步的装配点完成）。

**这是一次收紧（方向只允许更严）**：修复后，配了角色级 MFA 要求
却没有 Provider 的系统**会**在登录时 fail-closed。这不是验收标准的放宽，
而是把一个此前失效的安全分支接了回去。

### 14.3 两处实现缺陷（测试暴露 → 已修复）

| # | 缺陷 | 触发用例 | 根因与修复 |
|---|---|---|---|
| 1 | `create_item(is_default=True)` 遇同字典已有默认项时**撞数据库约束**（500 级） | `tests/test_dict_service.py::TestOneDefaultPerType::test_second_default_replaces_the_first` | `DictItemRepository.add()` 会 flush，而新行在**构造时就带 `is_default=True`** —— 旧默认项还在时插入即违反 `uq_sys_dict_item_type_default_active`。修复：把"清同字典默认项"提前到 `add()` **之前**（`update_item` 早已按此顺序写，并留有注释说明顺序为何重要，`create_item` 漏了） |
| 2 | `soft_delete_items` / `clear_default` 用 Core `update()`，**不维护身份映射** | `tests/test_dict_service.py::TestDictTypeCrud::test_delete_is_soft_and_cascades_items` | 实测发现 `synchronize_session` 的各种取值下，`status` 被同步而 `deleted_at` 不会（`RETURNING` 只取回主键时，SQLAlchemy 无法回填被改列的新值）→ 同一事务内 `session.get()` 返回 `deleted_at is None` 的**幽灵对象**，而库里那一行已经删了，且**响应体与审计有可能取自这个幽灵状态**。修复：改为 ORM 变更（按行加载后逐行赋值 + 显式 `flush()`）。字典项规模有界（`05 §3` 的唯一性本身就限制项数），代价可接受；同时删掉因此不再使用的 `count_items` / `list_item_ids` |

**通用规则（本 Phase 起适用）**：删除 / 批量写入路径**不得**用 Core `update()`
而不处理会话状态。要么用 ORM 变更，要么显式列出被改列并验证同步结果 ——
"库改了但会话没改"会让同一次请求里出现两个互相矛盾的事实。

### 14.4 公开字典查询的安全边界（细节）

`get_public` 的三个"不"（不写审计、不查数据范围、不接受 `actor`）
以及"`DISABLED` 与已删除一律 404"，理由逐条写在
`app/services/dict.py::get_public` 的 docstring 中。要点：

- 字典是**全局配置**，没有可限定的数据范围维度；
- 端点必须给出具体 `dictCode`，**无法**用来枚举"系统里有哪些字典"，
  因此不构成配置面泄漏；
- `DISABLED` 与"不存在"返回**同一个** 404：不把停用状态变成可探测信号。

### 14.5 MFA system 级默认值的迁移（`§12.1` 的兑现）

`docs/DESIGN-DECISIONS.md §12.1` 已裁定：Phase 5 保持环境变量
`MFA_REQUIRED_DEFAULT`，**Phase 7 迁入系统参数表**。本 Phase 的落地：

```text
参数键    mfa.required_default      （常量 MFA_REQUIRED_DEFAULT_KEY）
Seed 行   700001 / BOOL / ACTIVE / param_value=NULL / default_value='false'
取值      行存在 → 当前值 ?? 默认值
          行缺失 → 环境变量 MFA_REQUIRED_DEFAULT（= 迁移前口径，不制造可用性事故）
          行缺失会写一次 WARNING（进程内按键去重）
          行停用 / 类型不符 → ConfigurationError（fail-closed）
```

迁移前口径**完全保留**（行缺失即回退环境变量），因此"迁移脚本尚未执行"
不会变成"全员无法登录"；同时"删掉参数行"这一动作是有权限、有审计的
（`PARAM_DELETE`），"谁把安全开关删掉了"可追查。

代码常量、迁移 Seed 字面量与 Seed 主键三者的一致性由测试钉住
（`tests/test_param_mfa_binding.py::TestMigrationConsistency`）：改了常量
忘了 Seed 会让读取方**永远**走 fallback，且运行时几乎无法定位。

---

## 15. Phase 8（Dynamic Frontend Permission）—— 实际落地口径

### 15.1 登记表

| 编号 | 位置 | 取定 | 依据 / 未冻结来源 |
|---|---|---|---|
| **INTERIM-8-01** | `endpoints/permission_resources.py` 的路径 `/admin/permission-resources*` | kebab-case 复数资源名 | `08 §3–§9` **未列出**资源 CRUD 端点（DD-20 只说"HTTP 暴露属 008 范围"）。取与 `08 §5/§8` 既有复数资源（`sessions`、`dicts`、`audit/logs`）一致的命名 |
| **INTERIM-8-02** | `GET /auth/permissions` **不写**审计 | 只读本人快照、每次开页面都调 | 与 INTERIM-7-05（公开字典查询）同一取向：逐次审计会把审计表变成访问日志并稀释 FAILURE 信号 |
| **INTERIM-8-03** | 契约**不裁剪**空菜单 | 菜单本身是已授权资源 | 是否渲染"无可访问子页面的菜单"属前端策略；后端只保证下发的每一项都已授权，不替前端做渲染决策 |
| **INTERIM-8-04** | `GET /permission-resources/tree` 的 `resourceType` 缺失 → **400**而非返回空树 | 五种类型的树彼此独立 | 不指定类型时"构树"没有语义；返回空树会让调用方把"参数漏了"误读成"确实没有资源" |
| **INTERIM-8-05** | 响应 DTO 用 `snake_case`；请求/查询用 camelCase | 与既有 `PermissionPreviewResponse` / `RolePermissionViewResponse` 一致 | `08 §2` 未冻结字段命名；本 Phase 不引入第二套口径 |
| **INTERIM-8-06** | 六个角色授权端点写成**六条显式路由**而非 `/permissions/{kind}` | `08 §7` 冻结的是四条**具体路径** | 路径参数会让 OpenAPI 只出现一条，Phase 10 的契约比对将直接判缺失 |
| **JUDGMENT-8-01** | `is_super_admin == True` 时契约输出**全部 ACTIVE 资源**；**字段权限不做 bypass** | `10 §3` 冻结集中式 bypass | 见 §15.2 |
| **JUDGMENT-8-02** | `GET /auth/permissions` **不要求** API 权限位，但**要求已认证**且用**严格**依赖 | `08 §3` 把它列在 Auth 域 | 见 §15.3 |
| **FINDING-8-01** | 组织实体（users / departments / roles）CRUD 的 **HTTP 面至今未交付** | `08 §4/§6/§7` 已冻结清单 | 见 §15.4（登记为缺口，**不在本 Phase 越界补实现**） |

### 15.2 JUDGMENT-8-01 —— SUPER_ADMIN 在契约里的表达

`10 §3` 冻结了 SUPER_ADMIN 的**集中式 bypass**（`has_api_permission` 直接放行），
因此超管的"有效权限"在**事实层面**就是全部资源。若契约仍按
`role_permissions` 逐条读取，超管会得到**空集合** —— 前端渲染出一个空后台，
而真实授权是"全部"。那不是保守，而是**对授权状态的错误表述**，
且会让平台无法通过界面自助管理。所以 `is_super_admin` 为真时输出全部 ACTIVE 资源。

**字段权限刻意不做 bypass**，这是本判定里更重要的一半：
后端**没有任何**字段级 bypass（`field_policies` 的消费方目前只有本契约），
若超管额外得到"全部字段可编辑"，前端就会展示出后端实际并不承认的字段能力 ——
**契约与行为不一致，比"少显示"危险得多**。
因此字段策略对所有用户一视同仁地按"角色授权 + DD-06 最宽松者胜"输出，
未出现的字段按 HIDDEN 处理。

菜单与页面的**求交**（`09 §3` / `§4`）：
`menus[].page_ids = 菜单关联的 Page ∩ 用户已授权 Page`。
若不求交，前端会拿到指向"无权访问页面"的菜单入口，把"点进去被后端拒绝"
当成正常交互 —— 这正是 `09 §3` 禁止的"用前端隐藏冒充安全"的镜像错误。

### 15.3 JUDGMENT-8-02 —— `/auth/permissions` 为什么不需要 API 权限位

该端点返回的是**调用者本人**的权限快照。若要求某个 API 权限位才能读取，
会产生一个循环：客户端得先知道自己的权限，才能证明自己有权知道自己的权限；
而"没有权限"的用户连"我没有任何权限"这件事都读不到，
前端只能渲染成故障页而不是"无权限页"。

它仍然**要求已认证**，且使用**严格**依赖 `get_current_actor`
（处于强制改密状态的用户不可用）—— 该状态的客户端本来就只应调用
`/auth/me` 与 `/auth/password`，此时下发权限契约等于让它先逛后台再改密。

**没有**任何"目标用户"入参，目标恒为令牌所指的本人。
查看**他人**权限属权限预览（`03 §11`），是另一条需要授权的能力。

### 15.4 FINDING-8-01 —— 组织实体 CRUD 的 HTTP 面缺口（**未关闭**）

`08 §4/§6/§7` 冻结了 Users / Departments / Roles 的实体 CRUD 端点清单，
但仓库至今**只有服务层**，没有任何 HTTP 端点。原因是
`docs/verification/001` 与 `002` 的裁判项**全部是服务层判定**，
不包含端点存在性，因此 Phase 1 / Phase 2 验收 PASS 时不会暴露这个缺口。

**处置：登记，不在本 Phase 越界补实现。**
`PHASES.md` 的 Phase 8 范围明确是"权限输出（page/menu/button/api/field/data scope）"，
组织实体 CRUD 属 Phase 1 / Phase 2；在已 PASS 的阶段之外补实现会打乱阶段边界，
也使"哪个阶段交付了什么"不可追查。
但该缺口必须在 **Phase 10 Final Acceptance**（Functional: Organization / User / Role）
之前关闭，否则"后端全部做完"不成立。

**风险等级：中。** 服务层的能力与授权边界均已交付并被测试覆盖，
缺的是 HTTP 暴露面；不是安全缺陷，是**交付完整性**缺陷。

### 15.5 DD-21 的处理（**未冻结项，取保守实现，待人类追认**）

DD-21 台账标注"Phase 8 之前必须裁定"。按"继续执行、不得自行决定未决事项"
的边界，本 Phase **不改变任何既有行为**，只做两件事：

1. `EffectivePermissionService.build(allow_empty_roles: bool = False)` ——
   **默认 `False`，行为与 Phase 3 完全一致**（无有效角色仍抛错 fail-closed）。
   既有特征化测试 `test_default_build_still_fails_closed_for_role_less_user`
   直接钉住这一点。
2. 只有新增的**读路径** `/auth/permissions` 显式传 `allow_empty_roles=True`，
   得到"拒绝型上下文"（空权限 + `policy=null` + `department_ids=[]`）。

这样选择是因为：让"没配角色的正常用户"在打开后台时撞到 **500**
是产品语义问题而非实现细节，但**新增端点**没有历史行为要保护，
给它一个可渲染的"无权限页"既不违反已冻结的 fail-closed
（该用户依然什么都不能访问），也不会把 DD-21 的决定空间挤掉 ——
人类日后裁定"应抛 403"，改动面只是这一个端点的一个入参。

### 15.6 本 Phase 发现并修复的实现缺陷

| # | 缺陷 | 后果 | 修复 |
|---|---|---|---|
| 1 | 无有效角色用户的 `data_scope.department_ids` 曾返回 `null` | `null` 的语义是"部门维度**不限制**"（ALL / SUPER_ADMIN），等于把"全拒"表达成"全放行" —— 契约层面的 **fail-open**，且 JSON 里两者都"看起来像空" | `policy=null` 时 `department_ids` 恒为 `[]`；三态语义写进 `schemas/permission_contract.py` 的 docstring 并由 `test_role_less_user_still_gets_a_renderable_contract` 钉住 |
| 2 | `/permission-resources/tree` 若注册在 `/{resource_id}` **之后** | `tree` 会被当成 ID 交给 `int` 解析 → **422 而非 200**；两个装饰器各自都"正确"，只能靠真实请求发现 | 树路由声明在 ID 路由之前，并由 `test_tree_path_is_not_shadowed_by_the_id_path` 以**真实请求**钉住（只比对注册顺序不足以证明） |

### 15.7 与 Phase 9 的边界

`09 §7` / `00 §1#5` 的"权限变更立即生效"在本 Phase 以**实时计算、不使用任何缓存**
满足（结构上不可能陈旧），符合 Phase 3 对 DD-03 / DD-04 的裁定。
`009-hardening.md` 的"权限缓存有失效机制"将在 Phase 9 以
"**无缓存** ⇒ 无失效需求，且无 stale" 论证，而不是届时引入缓存。

---

## 16. Phase 9（Hardening）—— 实际落地口径

### 16.1 登记表

| 编号 | 位置 | 取定 | 依据 / 未冻结来源 |
|---|---|---|---|
| **INTERIM-9-01** | 限流阈值（登录 10/分/用户名、30/分/IP；MFA 20/分/IP） | 全部做成配置项，默认值取"挡得住自动化撞库、不影响正常使用"的量级 | **DD-10 未冻结**。冻结后只改环境变量，不改代码 |
| **INTERIM-9-02** | 限流键前缀 `rl:v1:<scope>:<sha256(subject)>:<window>` | 只放哈希，不放原始主体 | **DD-03（Redis Key 命名）未冻结**。本登记只覆盖限流这一类键，DD-03 对权限缓存仍开放 |
| **JUDGMENT-9-01** | Redis 不可用时限流 **fail-open** | 由 `settings.rate_limit_fail_open` 显式表达（默认 True） | 见 §16.2 |
| **JUDGMENT-9-02** | HSTS 默认**不下发** | `settings.security_hsts_enabled = False` | 见 §16.3 |
| **JUDGMENT-9-03** | CASCADE 外键采用**白名单**而非"一律禁止" | 目前仅 `mfa_challenges → admin_users` 一条 | 见 §16.4 |
| **FINDING-9-01** | JSON 形状的密钥**未被脱敏** | 已修复 | 见 §16.5（真实安全缺陷） |
| **FINDING-9-02** | `PUT /users/{id}` / `PUT /departments/{id}` 无法做部分更新 | 已修复 | 见 §16.6（真实数据破坏缺陷） |
| **FINDING-8-01** | 组织实体 CRUD 的 HTTP 面缺失 | **已关闭** | 见 §16.7 |

### 16.2 JUDGMENT-9-01 —— 限流在 Redis 不可用时 fail-open

选 fail-open 的理由**不是**"限流不重要"，而是**它在这里不是主防线**：

- 单账号暴力破解的主防线是 `04 §2` 的账号锁定（`failed_login_count` /
  `locked_until`），它**完全落在 PostgreSQL**，Redis 挂掉不影响它；
- 选 fail-closed 则 Redis 故障 = **所有人无法登录**，
  等于把登录可用性交给一个缓存组件 —— 这与本应用"启动 fail-soft、
  可用性由 readiness 探针表达"的既有取向相反。

因此 Redis 不可用时的结果是"退回账号锁定这一层"，不是"退回无保护"。

**IP 维度为什么不可省**：账号锁定只按账号计数，挡不住
"每个账号只试一次"的撞库，也挡不住"反复输错把别人账号锁死"的锁定 DoS。
两者只有 IP 维度能缓解；而 IP 维度挡不住分布式，所以账号维度也不能省。
两个维度防的是**不同的**攻击，任一个超限即拒绝。

**`request.client` 缺失时**（Unix socket / 某些代理链路）落到 `unknown` 桶，
而不是"不限流" —— 后者等于给"能隐藏自己来源"的调用方开一条绕行通道，
而那恰好是攻击者最容易走的一条。代价是所有未知来源共用一个桶，
相比"直接放行"仍是更严的选择。

### 16.3 JUDGMENT-9-02 —— HSTS 默认不下发

HSTS 是一个"一旦下发就难以撤回"的承诺：浏览器在 `max-age` 内强制 HTTPS。
若部署其实只在 HTTP 下工作（或某个内网健康检查端口只开 HTTP），
下发 HSTS 会把那个端口直接变成不可用。
因此它由部署方在**确认**全站 HTTPS 之后开启，不由代码默认决定。

其余四项（`nosniff` / `DENY` / `no-referrer` / `no-store`）无条件下发。
其中 `Cache-Control: no-store` 对本系统尤其重要：响应里有权限契约与用户列表，
一旦被缓存留存，"权限已变更"在缓存有效期内对客户端不可见 ——
那正好破坏 `09 §7` 的"权限变更立即生效"。

### 16.4 JUDGMENT-9-03 —— CASCADE 外键用白名单而非一律禁止

"零 CASCADE"看起来更严，但会把唯一一条合理的
（`mfa_challenges → admin_users`，瞬态挑战随用户清理）
逼成"不写理由就删掉"，反而让人以为 CASCADE 一律不可用。

因此改为**白名单断言**：CASCADE 集合发生变化时测试立刻失败，
迫使新增者先给出理由。当前白名单只有一条，且它在实践上不可触发 ——
物理删除用户会被其它 NO ACTION 外键（`sessions` / `user_roles`）挡住。

### 16.5 FINDING-9-01 —— JSON 形状的密钥未被脱敏（**真实安全缺陷，已修复**）

`app/core/masking.py::_SECRET_PAIR_RE` 原为 `键\s*[:=]\s*\S+`，
它只能命中 `password=hunter2` 这类"裸"写法。而结构化日志**最常见的形状是
JSON**：`{"password": "hunter2"}` —— 键名后紧跟一个 `"` 才是冒号，
于是整条密码**原样落库**。

这不是"少脱敏了一种格式"，而是漏掉了最常见的那一种。
修复：键名与冒号之间、冒号与值之间都允许可选引号，
值取到引号 / 空白 / 分隔符为止（不用贪婪 `\S+`，否则会吃掉值后的引号）。
已验证对 `password=` / `password:` / `password='..'` / JSON 全部生效且幂等。

**教训**：脱敏的测试只写了"我实现的那种形状"。
写这类用例时必须问"生产日志里它**实际**长什么样"。

### 16.6 FINDING-9-02 —— PUT 无法做部分更新（**真实数据破坏缺陷，已修复**）

`UserUpdateRequest.department_id` 与 `DepartmentUpdateRequest.parent_id`
默认值为 `None`，端点原本把 `payload.x` 原样传给服务层，
于是"只想改个显示名"被解释成"顺便把用户移出部门"：

- 非全局数据范围 → 直接 403（明显，但**改不动任何字段**）；
- 全局数据范围 → **静默把用户移出部门**，没有任何报错。

服务层其实已经支持三态（`_Unset` 哨兵），缺的是端点正确分派。
修复：用 `model_fields_set` 判断客户端**实际**提交了哪些字段，
未提交的显式传 `UNSET`（已把哨兵从私有 `_UNSET` 公开为 `UNSET`）。

**教训**：`Optional[...] = None` 在 DTO 里天然是二义的。
凡是"显式 null 有独立业务含义"的字段（清空、移出、移到根），
端点必须按 `model_fields_set` 分派，不能图省事直接透传。

### 16.7 FINDING-8-01 —— 组织实体 CRUD 的 HTTP 面（**已关闭**）

`08 §4` / `§6` / `§7` 冻结的 Users / Departments / Roles 实体端点已在
Phase 9 补交付：`endpoints/users.py`（7 条）、`endpoints/departments.py`（4 条）、
`endpoints/roles.py`（3 条），全部声明式绑定
`USER_MANAGE` / `DEPARTMENT_MANAGE` / `ROLE_MANAGE`。

新增两个权限位（`ApiPermissionCode.USER_MANAGE` / `DEPARTMENT_MANAGE`），
读与写共用一个位，理由与 `DICT_MANAGE` 同：用户/部门清单本身是敏感信息，
且 `03` 未给出相应资源编码表，拆细只会增加待冻结项。

**刻意没有**补 `DELETE /users/{id}` 与 `DELETE /departments/{id}` ——
`08 §4` / `§6` 的冻结清单里没有它们。服务层有能力（`delete()`）
不等于契约允许暴露；自行加一条等于在没有需求的地方发明 API 面。
角色的删除沿用冻结的 `POST /roles/{id}/delete`（不是 `DELETE`）：
本系统的删除是**逻辑删除**，用 `DELETE` 会让"已不存在"与"已停用"
在协议层无法区分。

### 16.8 与 Phase 9 裁判项的对应

| 裁判项 | 结论 | 说明 |
|---|---|---|
| 权限缓存有失效机制 | **PASS（无缓存）** | 结构上不存在缓存，故无失效需求；用 AST/属性断言钉住"不得出现缓存痕迹" |
| 权限变更无明显 stale permission | **PASS** | 连续两次构建之间无需任何失效动作 |
| 关键写操作具备幂等策略 | **PASS** | DD-11 方案 A（语义幂等）已冻结并落地 |
| 并发更新有保护 | **PASS** | 见 §16.9 |
| 登录 / MFA 有必要的 rate limit | **PASS** | 新增 `app/core/rate_limit.py` |
| 错误响应不泄漏内部异常 | **PASS** | 既有 `handle_unexpected_error` + 422 丢弃 `input` |
| Secret 不进入日志 | **PASS（修复后）** | FINDING-9-01 |
| Migration 可重复部署 | **PASS** | 见 §16.10 |
| 数据库关键索引存在 | **PASS** | 实查 82 条索引、11 条 partial index |
| FK 行为符合逻辑删除设计 | **PASS** | CASCADE 白名单（仅 1 条） |
| 安全审查无高危未解决项 | **PASS** | 见 §16.11 |

### 16.9 关于"并发"这一项的诚实边界

本阶段的并发用例证明的是**保护机制存在且生效**
（`rotate_tokens` 的 CAS 条件更新使第二个写入者匹配 0 行；
`record_retired_refresh_token` 的 `ON CONFLICT DO NOTHING` 让并发下必然
重复的留档不再抛错），而**不是**在多线程/多连接下做竞态压测 ——
`db_session` 夹具把每个用例包在一个事务里并在结束时回滚，
两任务的"并发"会共用同一条连接从而被串行化，
那样跑出来的"并发测试"是假的。真正的竞态压测需要独立连接池与已提交的数据，
属压测环境范畴，**不在此伪造**。

此外，整体替换型端点（`PUT .../permissions/pages`）上的
last-write-wins 是**安全的**：请求体是完整集合，
后到者覆盖先到者时结果仍是某个请求者的完整意图，
而不是两者各半的混合体。这是"此处不需要乐观锁"的依据，已由测试钉住。

### 16.10 关于"Migration 可重复部署"的验证边界

已验证：

- **正向幂等**：`alembic upgrade head` 在已迁移的库上是 no-op（版本表追踪）；
- **无漂移**：`alembic check` → `No new upgrade operations detected.`；
- **回滚路径存在**：每个 `upgrade()` 有操作的迁移，其 `downgrade()` 也必须
  有操作（空实现会让 `alembic downgrade` 静默成功却什么也没撤）。
  baseline 迁移两者皆空（`upgrade()` 什么也不建），属合法例外。

**未**执行完整的 `downgrade base → upgrade head` 循环：
远端 PostgreSQL 是共享实例，跑降级会**抹掉全部数据**。
该循环应在独立的临时库上验证，不在此冒险。

### 16.11 安全审查结论

本阶段修复了 2 个真实缺陷（FINDING-9-01 密钥脱敏漏掉 JSON 形状、
FINDING-9-02 部分更新被当成清空），关闭了 1 个交付缺口（FINDING-8-01）。
未发现新的 P0 / 高危未解决项。RISK-004（SUPER_ADMIN 判定口径）
仍为已登记未冻结项，不属本阶段范围。

## 17. Phase 10（Final Acceptance）—— 实际落地口径

### 17.1 登记表

| 编号 | 位置 | 取定 | 依据 / 未冻结来源 |
|---|---|---|---|
| **FINDING-10-01** | `08 §8` 的审计 / 链路**读**端点完全缺失 | 已补交付 4 条端点 | 见 §17.2（**交付缺口，非安全漏洞**） |
| **FINDING-10-02** | `GET /users/{id}` 的 docstring 写"按不存在处理"，实现返回 403 | 已修正文档（**不改实现**） | 见 §17.3 |
| **INTERIM-10-01** | 日志**不**应用数据范围 | 可见性只由 `AUDIT_READ` / `TRACE_READ` 权限位承担 | `10 §10` 的数据范围围绕 `department_id` 定义，而五张日志表没有该列 |
| **INTERIM-10-02** | 两个新权限位 `AUDIT_READ` / `TRACE_READ` | 与 `PARAM_MANAGE` / `DICT_MANAGE` 的分离同理 | `03` 未给出日志相关的资源编码表 |
| **INTERIM-10-03** | 两个新审计动作 `AUDIT_LOG_READ` / `AUDIT_TRACE_READ` 归入 **READ_ONLY** | 与审计表同寿命（2 年） | 见 §17.4 |
| **DEBT-10-01** | 10 条（18 个 operation）管理端点把授权绑在**服务层**而非路由层 | 登记为技术债，以全路由护栏防止扩大 | 见 §17.6（**不是安全缺口**：`08 §10` 已满足） |
| **DEBT-10-02** | `/auth/permissions` 的路径：08 写 `/auth/permissions`，09 写 `/api/v1/admin/auth/permissions` | 实现取 **08** 的版本；09 是**冻结 Spec**，不自行改动 | 见 §17.7（需人类决定"改文档"还是"加别名"） |

### 17.2 FINDING-10-01 —— `08 §8` 的四条端点此前一条都没有

`08 §8` 冻结：

```text
GET /audit/logs
GET /audit/logs/{id}
GET /traces
GET /traces/{traceId}
```

但 Phase 6 的验收裁判（`006-logging-audit.md`，35 项）**全部是落库判定** ——
五类日志写不写得进、字段齐不齐、保留期对不对 —— 没有任何一项问
"能不能把它们读出来"。于是那次 PASS 不会暴露"日志只进不出"：
系统能**记**，却没有 HTTP 端点能**查**，运维只能直连数据库。

这与 FINDING-8-01（Users / Departments / Roles 实体 CRUD 缺 HTTP 面）
是**同一类缺口的第二次发生**，根因相同：

> **裁判项只判服务层，于是"HTTP 面不存在"永远判不出来。**

两处的补救都附了"防再犯网"：路由面被**逐条钉住**
（`tests/test_log_query_api.py::TestRouteSurface`、
`tests/test_organization_api.py::TestRouteSurface`），
端点消失会立刻变红，而不是靠下一个人再发现一次。

补交付内容：

- `app/repositories/log_query.py`——读侧仓储（**单独一个模块**，
  理由见其模块文档：`LogRepository` 的定位是落库，两者关注点不同）；
- `app/services/log_query.py`——归一化 + 成功审计；
- `app/api/v1/endpoints/audit_logs.py`——4 条端点；
- `tests/test_log_query_api.py`（13 例）。

两个刻意的设计取舍：

1. **`GET /traces/{traceId}` 不分页**：一次请求的日志条数有天然上界，
   且"看清一次请求做过什么"要求它们一起返回；
   单张表的条数上界由 `TRACE_ENTRY_LIMIT_PER_TABLE = 500` 兜住。
2. **链路回放走五次查询而不是一条 `UNION ALL`**：五张表的列集合本质不同，
   归一化成一条 SQL 需要补 `cast(None, ...)` 空列，
   那会把"这张表没有这个字段"从类型系统里抹掉。排障路径是低频的，
   能走索引与保住类型检查比省 4 次往返重要。

### 17.3 FINDING-10-02 —— 文档与实现不符（**改文档，不改实现**）

`endpoints/users.py::get_user` 的 docstring 写着
"范围外用户按不存在处理（不泄露存在性）"，但 `UserService.get`
对范围外目标抛 `PermissionDeniedError` → **403**。

裁定：**403 是正确的，改的是文档**。理由：

- 403 附带一条 **FAILURE 审计**，留下"谁试图访问谁"的取证记录；
  改成 404 会让这类探测在审计里彻底消失 —— 那是**削弱**而不是收紧；
- 列表接口与单读接口表现不同是**有意的**：列表把范围下推到 SQL（看不见，
  防的是数据外泄），单读明确拒绝（看得见但拒绝，留下的是取证）。
- Phase 2 的 `test_read_out_of_scope_user_is_denied` 已按 403 钉住该行为。

### 17.4 INTERIM-10-03 —— 为什么"读日志"归入 READ_ONLY 而不是 SECURITY

`SESSION_READ` 当初进了 `SECURITY_ACTIONS`（会话元数据含 IP / UA）。
按同一直觉，"读审计"似乎更该进安全类。本次取**相反**的方向，理由是保留期：

- 安全日志保留 **180 天**，审计日志保留 **2 年**；
- 若"谁读过审计"随安全日志在 180 天后消失，那么 2 年内的老审计记录
  就再也回答不了"它被谁访问过" —— 取证链条会缺一截。

放进 READ_ONLY（仅审计表、留存 2 年）才能让"读审计"与"审计本身"同寿命。
反方向的风险已登记：若人类认为查审计属 `06 §1` 的安全事件，
改动是把这两个动作在两个集合之间搬一次。

### 17.5 关于"数据范围不适用于日志"的安全代价（INTERIM-10-01）

代价是明确的：**能查审计的人看得见全部审计**，包括跨部门的操作记录。
缓解方式是"权限位必须显式授予"，而不是靠范围再切一刀 ——
因为给日志发明一套按部门过滤的范围会**削掉跨部门操作**，
而跨部门恰恰是最需要被看见的部分（一次越权尝试往往正是跨部门的）。

### 17.6 DEBT-10-01（技术债，非缺陷）—— 部分端点把授权绑在服务层

全路由授权护栏（本次新增）扫出 **10 条相对路径**（展开后 18 个 operation）
没有路由层的 `require_api_permission` 声明：

```text
Phase 5：/sessions、/sessions/{id}/revoke、
         /users/{id}/sessions、/users/{id}/sessions/revoke-all
Phase 7：/dicts*（9 个 operation）、/params*（5 个 operation）
```

**它们不是未授权**：这些端点的服务层调用
`assert_can_manage_sessions` / `assert_can_manage_dicts` / `assert_can_manage_params`，
三者最终都走 `assert_api_permission` —— `08 §10` 是**满足**的。
白名单表达的是**绑定位置不一致**（服务层而非路由层），不是安全缺口。

为什么不直接在 Phase 10 把它们统一到路由层：
本阶段已完成全部 29 项验收判定，此时改动 Phase 5 / Phase 7 的**已验收**端点
（会改变 FAILURE 审计的写入位置：路由层而非服务层）需要重跑那两个阶段的验收，
而收益只是风格统一。因此按**技术债登记**而不是当作缺陷硬改，
并用护栏保证它**不再扩大**。

护栏：`tests/test_route_authorization_guard.py`（5 例）

- 新增一条未声明授权的管理端点 → **失败**；
- 修好一条遗留端点 → 集合变小 → 仍然通过（白名单用**子集**断言，
  不惩罚改进）；
- 白名单里的路径若已被删除/改名 → 失败（防止清单变成僵尸）；
- 另有一条**自检**用例：扫描到的 admin 路由少于 40 条就红 ——
  没有它，"扫到了 0 条"会被子集断言判成通过，
  那是一条**永远绿的护栏**，比没有护栏更危险。

> 顺带修掉了 DD-20 §5.1.3 里一直没落地的那半句话：
> "漏声明的路由可以被静态扫描出来"。此前没有任何机制能做到这件事，
> 而 FINDING-8-01 与 FINDING-10-01 都是"没人扫描"的直接后果。

### 17.7 两个新权限位为什么不合并成一个

`AUDIT_READ` 与 `TRACE_READ` 分开，理由与 `PARAM_MANAGE` / `DICT_MANAGE`
的分离同理：`GET /traces/{id}` 会返回**应用日志正文**与访问日志
（路径 / 状态码 / 耗时），信息面比审计表宽得多。
若"能查审计"隐含"能看链路"，那么任何只读审计权限的账号
都能读到全部应用日志 —— 那是一次**静默的权限放大**。
`tests/test_log_query_api.py::TestAccessControl::test_audit_read_does_not_imply_trace_read`
专门钉住这一点。

### 17.7 DEBT-10-02（Spec 内部冲突，非实现缺口）—— `/auth/permissions` 的路径两处说法不一致

本次做"冻结契约 ↔ 路由面"覆盖审计时扫出：

```text
08-API规范.md:40    GET `/auth/permissions`
09-前端动态权限.md:11  GET `/api/v1/admin/auth/permissions`
```

两份 Spec 都是**已冻结**的，实现取的是 **`/api/v1/auth/permissions`**（与 08 一致），
Phase 8 / Phase 10 的验收也是按这个路径判定的。

为什么实现不取 09 的版本：

1. `/auth/permissions` 是"**当前登录者查自己**"的端点，
   与 `/auth/me` 同类，挂在 `/admin` 下会让"自己看自己"变成"管理员操作"；
2. 09 是 Phase 8 才纳入的 Spec，08 是 API 面的**总纲**；
   两者冲突时以总纲为准，这是本项目既有的取定习惯
   （同类：`INTERIM-8-01` 的路径推导也以 08 为准）；
3. 09 的第 11 行在语法上更像是把 08 的相对路径误粘进了 §2 的绝对地址段落
   （同一段里其余条目没有写 `/api/v1` 前缀）。

**不改动冻结 Spec**，登记为待裁项：若要让 09 与实现对齐，
需要人类决定是"修改冻结的 09"还是"为该端点增加 `/admin` 别名"。
前者是文档修订，后者是**凭空新增 API 面**，两者都不是我能在无人拍板时做的选择。

---

## 18. Phase 11（Admin Frontend）—— 实际落地口径

### 18.1 登记表

| ID | 内容 | 状态 |
|---|---|---|
| `INTERIM-11-01` | E2E 种子的 API 资源编码必须与 `ApiPermissionCode` 逐字一致 | 技术决策，**未冻结** |
| `OPERATION-11-01` | `scripts/seed_e2e.py` 与测试套件共用同一个数据库 | 操作约定，非设计决策 |
| `BLOCKED-11-01` | 真实浏览器 E2E 不可用（`BLOCKED_BY_ENVIRONMENT`） | 环境阻塞，不冒充 PASS |

### 18.2 INTERIM-11-01 —— E2E 种子的资源编码必须与 `ApiPermissionCode` 对齐

`scripts/seed_e2e.py` 的 `APIS` 最初写的是自造编码（`api:user:list` /
`api:user:create` / `api:department:list` …）。这些编码**没有任何端点认** ——
后端用的是 `app.services.authorization.ApiPermissionCode`（`USER_MANAGE` /
`DEPARTMENT_MANAGE` / `ROLE_MANAGE` …）。

后果是"权限界面上明明勾满了，接口照样 403"，而 403 的报错信息只说
"缺少 USER_MANAGE"，看不出是自造编码没对上 —— 这类缺陷在只跑清单核对的验收里
**永远不会被发现**。

现改为逐字使用 `ApiPermissionCode` 的取值。

约束（后续改动必须遵守）：

1. 新增受保护端点时，`require_api_permission` 的入参必须**同时**出现在
   `scripts/seed_common` 所引用的那张 API 清单里（现由 `scripts/seed_data.py`
   作为唯一来源），否则种子里的授权角色会被静默降级；
2. `permission_resources` 的唯一键是 `(resource_type, resource_code)`，
   一个权限码只能写一行；
3. `api_path` 取**后端完整路由去掉 `settings.api_v1_prefix` 之后的相对路径**。
   ⚠️ `settings.api_v1_prefix` 本身已经是 `/api/v1/admin`
   （`app/core/config.py`），因此写 `/users` 而不是 `/admin/users`。

   这一条在最初登记时写成了"/admin/users 这种相对路径"，是**错的**：
   `settings.api_v1_prefix` 已经把 `/api/v1/admin` 吃掉了，再补一个 `/admin/`
   就成了双前缀。`tests/test_seed_data.py` 的
   `test_api_paths_and_methods_are_real_backend_routes` 一上线就抓出全部
   9 条路径都写错了（`GET /admin/users` 实际是 `GET /users`），
   其中部门那条更严重 —— `GET /admin/departments` 这个端点**根本不存在**，
   部门列表只以 `GET /departments/tree` 提供。

### 18.3 OPERATION-11-01 —— `seed_e2e.py` 与测试套件共用同一个数据库

本机的 PostgreSQL 是**远程共享实例**，测试套件与 E2E 种子都写它。
`seed_e2e.py --reset` 会清空 `roles` / `admin_users` / `permission_resources` /
`department` / 会话等表，而 `tests/conftest.py` 自己往同样的表里塞夹具
（例如 `tests/test_session_management.py` 会建一个固定
`role_code="SUPER_ADMIN"` 的角色）并**期望库里没有同名行**。

在测试库上跑一次 `--reset`，下一轮 pytest 会以 **412 个失败**开场 ——
那些失败与代码无关，纯粹是数据被自己清掉了。

因此：

- `--reset` 保留，但只应用于**独立的 E2E 库**；
- 新增 `--unseed`：**按业务键**只删本脚本写过的行（用户 / 角色 / 资源 /
  部门及其关联），不影响其它数据；已实现并用抽样测试验证还原成功；
- 明确要求：E2E 与测试套用**不同的数据库**；若必须共用，跑测期间禁止执行本脚本。

### 18.4 BLOCKED-11-01 —— 真实浏览器 E2E 不可用（`BLOCKED_BY_ENVIRONMENT`）

`FE-12 §4` 要求"至少 SUPER_ADMIN、DEPARTMENT_ADMIN、普通用户"三角色验证。
本机 Playwright **未安装任何浏览器**（`~/.cache/ms-playwright` 不存在），
因此浏览器级 E2E 无法执行。

处理：

1. 移除 `package.json` 中指向空目录的 `"e2e": "playwright test"` 脚本与
   `@playwright/test` 依赖 —— 一个跑不起来的门禁比没有门禁更危险，
   它会让人误以为 E2E 已经通过；
2. E2E 以**契约级**方式交付：`scripts/seed_e2e.py` + `scripts/e2e_three_roles.py`，
   对真实后端发真实 HTTP，**50 项判定全绿**；
3. 该结论**不含渲染层**，浏览器级用例补齐前不视为完成。

### 18.5 本阶段修复的实现缺陷

| 缺陷 | 症状 | 根因 |
|---|---|---|
| 登录页永远打不开 | 未登录访问 `/login` → `infinite redirect` | `decideNavigation` 未放行登录页自身 |
| 登出只清了一半 | 登出后旧账号的动态路由仍在 | `clearSession()` 未连带清权限与路由 |
| 三层菜单塌成平级 | 侧边栏层级全乱 | 挂点落到"父的挂载点"而非"父节点" |
| 授权了却照样 403 | E2E 里自造编码不被识别 | 见 `INTERIM-11-01` |
| 菜单一个都没给 | 页面全给、菜单全无 | `menu_for_page in resource_id` 恒 False（键为二元组） |

## 19. 初始数据（Initial Data）—— 实际落地口径

### 19.1 登记表

| ID | 内容 | 状态 |
|---|---|---|
| `OPERATION-19-01` | `scripts/seed_data.py` 是初始数据清单的**唯一来源** | 操作约定，非设计决策 |
| `INTERIM-19-01` | 初始管理员的**创建时机** | 技术决策，**未冻结** —— 当前实现：口令必须由 `SEED_INIT_ADMIN_PASSWORD` 注入，缺省则报错退出；待定的是"是否改为 `--with-admin` 缺省即静默跳过" |

### 19.2 OPERATION-19-01 —— 清单与写入拆分，两份种子共用

背景：`alembic upgrade head` 之后库是**空的** —— 没有部门、角色、权限资源，
也就没有任何人能登录，连进管理界面改数据的人都没有。

因此新增 `scripts/seed_init.py`（全新部署入口），并把清单从 `seed_e2e.py`
抽到 `scripts/seed_data.py`：

- `scripts/seed_data.py` —— **纯数据**（部门 / 角色 / 资源 / 授权映射）；
- `scripts/seed_common.py` —— **写入实现**（两个脚本共用）；
- `scripts/seed_init.py` —— 全新部署入口（骨架 + 可选初始管理员）；
- `scripts/seed_e2e.py` —— E2E 三角色种子（改动实现，清单改为 import）。

理由：`seed_init` 与 `seed_e2e` 需要的骨架几乎相同，两份各写一份必然漂移，
而漂移是**静默**的（`18.2` 已经因此出过一次事故）。

约束（后续改动必须遵守）：

1. **新增 / 改资源编码只改 `scripts/seed_data.py`**；
2. 新增种子内容时，写入逻辑放 `seed_common.py`，`seed_init.py` 与
   `seed_e2e.py` 都调用它；
3. pytest 的 `pythonpath` 必须包含 `scripts/` —— 否则测试拿到的是与脚本
   **另一个副本**的模块对象，两边各改一处就会静默不一致。

### 19.3 幂等口径：统计的是"本次实际新建行数"

`--dry-run` 与实跑走**完全相同**的代码路径，只在最后 `rollback()`，因此
"预演成功"意味着"真跑也一定成功"；但同一事务内反复跑看不出"已提交过"的状态，
所以 `tests/test_seed_common.py` 用 `db_session` 夹具（外层事务 + 结束回滚）
**跑两遍**，第二遍要求新建数归零且不抛异常。

该用例在写上显式 `flush()` 之前是**空过**的：夹具是 `autoflush=False`，
不落库的话第二遍读到的仍是空表。这正说明"断言跑过了"与"断言有效"是两件事。

### 19.4 本批次实现/验证中修复的缺陷

| 缺陷 | 症状 | 根因 |
|---|---|---|
| 第二次执行必崩 | `IntegrityError: duplicate key violates pk_role_field_permissions` | 授权函数只 `add()` 不查，而两张授权表是复合主键、无 upsert 余地 |
| 台账指向不存在的端点 | `GET /admin/departments` 404（真实只有 `/departments/tree`） | API 路径口径写错，漏算 `settings.api_v1_prefix` 已含 `/api/v1/admin` |
| 幂等用例空过 | 第二遍断言"0 新建"恒真 | `autoflush=False` 下计数查询不触发 flush，重复写入从未落库 |
| 授权清单漂移风险 | 两个脚本各写一份清单 | 已拆为 `seed_data.py` 唯一来源 |

## 20. 前端 UI 组件库 —— **已裁定：naive-ui**

`docs/frontend-spec/FE-00-前端总体需求.md §6` 原把「UI 组件库」列为未冻结项，
Agent 不得擅自决定。**2026-09-26 由用户显式要求引入** —— 该未冻结项就此关闭。

### 20.1 登记表

| ID | 内容 | 状态 |
|---|---|---|
| `DD-22 UI 组件库` | 选定 naive-ui 作为交互件底座，CSS 框架仍不引入 | **已冻结**（用户裁定） |
| `OPERATION-20-01` | 全站色值只在 `frontend/src/styles/theme.ts` 定义一次 | 操作约定，**必须遵守** |

### 20.2 选型理由

候选：Element Plus / Ant Design Vue / Arco / naive-ui。

选 **naive-ui**：

1. **完全用 TypeScript 编写**，`themeOverrides` 有完整类型，选本项目
   （`vue-tsc` 严格模式）最看重这一点；
2. **主题重写作用在 JS 侧**，能与本项目的 CSS 变量体系对齐成一套，
   而不是"组件库一套色、手写 CSS 另一套色"；
3. 自带 `zhCN` 语言包与 `dateZhCN`，不需要另接 i18n；
4. 组件尺寸（`size="small|medium|large"`）与"后台密集型界面"契合。

**仍然不引入 CSS 框架**（Tailwind 等）：布局与容器类样式保持手写，
以便精确控制观感，也避免为第三方类名再写一遍设计 token。

### 20.3 OPERATION-20-01 —— token 唯一来源

`applyCssTokens()` 把这批值**内联写到 `:root`**，`base.css` 里不再有
`:root` 色值块。内联样式优先级高于任何 CSS 选择器，因此"TS 是唯一真值"
在运行时也成立。

驱动这一次的具体事故不在 CSS，而在 19.2 的种子清单：两份同源内容各写各的，
改一处另一处静默失效。色值同属"看起来无害但实际会漂"的那一类。

### 20.4 引入组件库时必须同时改的三件事

1. **测试若按 DOM 位置断言，必须重新核对**：
   naive 的 `NModal` 会 teleport 到 `body`，`wrapper.find('[role="dialog"]')`
   会落空 —— 但 `role="dialog"` 语义**没有丢**，所以要改的是查询位置，
   不是放弃这条断言。
2. **teleport 容器必须清理**：Modal / Message / Drawer 的容器不会随
   `wrapper.unmount()` 消失，会污染后续用例。已在 `tests/setup.ts` 的
   `afterEach` 里统一移除。
3. **别给已经换成组件的元素继续写外观**：曾经给 `.pagination__btn`
   写了边框和背景，换 `NButton` 后两层样式互相抢优先级，
   表现是"hover 只有一半生效"。这类类现在只保留布局职责。

### 20.5 本批次实测记录

- `npm run typecheck` / `lint` / `vitest`（175 例）/ `vite build` 全绿；
  产物 `index-*.js` 326.84 kB（gzip 108.10 kB）。
- 变异验证：撤掉确认弹窗的 `emit('confirm')` →
  「写操作之后树被重拉」用例确实变红（`expected spy to be called 1 times, but got 0`）。
- 视图层重复样式**已清理**：`mini-table` 10 份、`editor` 7 份、`toolbar` 6 份
  `alert` 6 份等 scoped 定义已删除，统一由 `base.css` 的共享类承担；
  system 视图的 scoped 样式从约 618 行降到 49 行（只剩各自独有类：
  `picker` / `group` / `depts` / `cell` / `cell-actions`）。
  差异靠**变量与修饰符**表达而不是靠重抄一遍：链路详情抽屉原本重写整个
  `.drawer__panel` 只为改宽 760px，现在只设 `--drawer-width`。
- 清理时踩到两件事，记在这里防再犯：
  1. 脚本化删除必须**按选择器清单白名单**做。这次误把仍在使用的 `.depts`
     当成全局类删了（模板第 402 行还在用）—— **CSS 删错不会让测试变红**，
     只有回头核对剩余 style 段才能发现；
  2. 跨行合并选择器（`.tree,\n.sub-panel {…}`）用简单的按行解析会漏判，
     第二轮才删干净。删完要逐个文件看余下的 style 段，不能只看脚本日志。
