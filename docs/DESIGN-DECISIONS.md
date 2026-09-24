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
| **DD-01** | **MFA Provider** | **已冻结（方案 A，2026-09-24）**：Phase 4 落地步骤 + Provider 抽象 + fail-closed；具体 Provider 留 Phase 5 | Phase 5（005）落地实现 |
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
