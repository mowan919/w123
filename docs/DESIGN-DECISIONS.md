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
