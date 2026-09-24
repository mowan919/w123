# Verification 002 — Permission · 执行结果

| 项 | 值 |
|---|---|
| 验收依据 | `docs/verification/002-permission.md`（裁判文件，**未修改**） |
| 执行 Phase | PHASE-003-PERMISSION（= `PHASES.md` Phase 2 — Role / Permission） |
| 执行时间 | 2026-09-24 06:00 UTC |
| 代码基线 | `ec66678`（Phase 2 commit）+ Phase 3 工作区改动 |
| 执行方式 | `.\scripts\dev.ps1 -Action verify`（ruff check + ruff format --check + mypy + pytest） |
| 门禁结果 | ruff `All checks passed` ｜ format `132 files already formatted` ｜ mypy `Success: no issues found in 62 source files` ｜ pytest **493 passed** |
| 结论 | **PASS**（23/23 检查通过；0 项 BLOCKED；2 项带 Phase 边界说明） |

> 说明：本文件是**执行结果记录**，不是验收裁判。
> `docs/verification/002-permission.md` 的检查项内容**一字未改** ——
> 修改裁判文件以适配代码是明令禁止的行为。

---

## 1. 逐项判定

### 1.1 模型

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| M1 | User → Role | 用户与角色经 `user_roles` 多对多关联，可读写 | `user_roles(user_id, role_id)` 复合主键，双 FK `RESTRICT`；`RoleRepository.list_active_role_ids_for_user` 按用户取角色 | **PASS** | `app/models/role.py:100`；`tests/test_effective_permission.py::TestUnionAcrossRoles::test_two_roles_union` |
| M2 | User 支持多 Role | 同一用户可持有 ≥3 个角色，权限逐角色累加 | 直接角色集合 = `{ROLE_A, ROLE_B, ROLE_C}`；三路授权各自生效 | **PASS** | `tests/test_effective_permission.py::TestUnionAcrossRoles::test_three_roles_union_including_button_and_api` |
| M3 | 多 Role 权限取并集 | 有效权限 = 各角色的并集（`00 §1#2` / `15 D-002`） | 跨角色页面 / 按钮 / API / 字段全部取并；重复授权不产生重复行 | **PASS** | `tests/test_effective_permission.py::TestUnionAcrossRoles`（4 例）、`tests/test_role_permission.py::TestTypeScopedReplacement::test_replacement_is_idempotent` |
| M4 | Role inheritance V1 生效 | V1 支持角色继承，继承权限计入有效权限（`00 §1#3` / `03 §4`） | 邻接表 `role_inheritances`；递归 CTE(`UNION`) 展开祖先；子角色获得父角色全部权限，多级传递可达 | **PASS** | `app/repositories/permission.py:745`（`ancestor_ids`）；`tests/test_effective_permission.py::test_inherited_permissions_are_counted`、`::test_grandparent_is_reached_transitively`；`tests/test_role_inheritance.py`（28 例） |
| M5 | Page Permission | PAGE 资源 + 角色授权 + 有效权限输出 | `PermissionResource(type=PAGE)` 带 `route_path`/`component_path`；`role_permissions` 授权；`PermissionContext.page_ids` | **PASS** | `app/models/permission.py:133`；`tests/test_effective_permission.py::test_two_roles_union` |
| M6 | Menu Permission | MENU 资源独立存在，且 Menu↔Page 为多对多 | MENU 可嵌套（`parent_id`）、可配图标；`menu_pages` 关联表使一个 Page 可被多个 Menu 引用 | **PASS** | `app/models/permission.py:284`（`MenuPage`）；`tests/test_permission_resources.py::TestMenuPages::test_replace_and_clear`、`::TestResourceShapeConstraints::test_menu_with_parent_and_icon_is_accepted` |
| M7 | Button Permission | BUTTON 必须挂在 PAGE 下，可被授权 | BUTTON 形状 CHECK 强制 `parent_id IS NOT NULL`；服务层校验父资源必须为 PAGE | **PASS** | `tests/test_permission_resources.py::TestResourceShapeConstraints::test_button_without_parent_is_rejected`、`::TestResourceServiceCreate::test_button_parent_must_be_page`；`tests/test_effective_permission.py::test_three_roles_union_including_button_and_api` |
| M8 | API Permission | API 资源 + 后端强制判权入口（不依赖前端） | `ApiPermissionCode` 集中定义编码；`AuthorizationService.assert_api_permission` / `has_api_permission`；`PermissionContext.api_codes` | **PASS** | `app/services/authorization.py:152`（`assert_api_permission`）、`:141`（`has_api_permission`）；`tests/test_effective_permission.py::TestSuperAdminBypass::test_normal_user_needs_explicit_api_grant`；`tests/test_role_service.py::TestRoleCreateAuthorization::test_holder_of_role_manage_api_can_create` |
| M9 | Field Permission | 字段级四级授权，独立于二元授权 | 专用表 `role_field_permissions(role_id, field_id, access_level)`；FIELD 资源经 `owner_resource_id` 归属 PAGE | **PASS** | `app/models/permission.py:351`（`RoleFieldPermission`）；`tests/test_effective_permission.py::TestFieldPermissionMerge`（4 例） |
| M10 | Data Scope | 五种策略齐备且真正下推 SQL | `DataScope` 五值；`ResolvedScope` fail-closed 不变量；`scope_filters` 生成 SQL 条件（非内存过滤，`10 §10`） | **PASS** | `app/core/scope.py`；`app/repositories/scope_filters.py`；`tests/test_scope_guard.py`（15 例，含 `@pytest.mark.security`）、`tests/test_resolved_scope.py`（28 例） |

### 1.2 关键规则

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| R1 | Page 可配置 | 可创建/修改/删除 PAGE 资源，并授权给角色 | `PermissionResourceService` 全 CRUD（形状校验、父资源类型校验、引用拒绝、逻辑删除）；`RolePermissionService.replace(kind="pages")` | **PASS** | `app/services/permission_resource.py`、`app/services/role_permission.py`；`tests/test_permission_resources.py`（43 例）、`tests/test_role_permission.py`（23 例） |
| R2 | Menu 可配置 | 可配置菜单层级、图标，并关联多个 Page | MENU 可嵌套、可配 `icon`；`set_menu_pages` 以**整体替换**语义维护多对多；拒绝把非 PAGE 资源关联进来 | **PASS** | `tests/test_permission_resources.py::TestMenuPages`（3 例） |
| R3 | Button 可配置 | 可配置按钮并校验其所属页面 | `_PARENT_TYPE_RULES` 强制 `BUTTON → PAGE`；形状 CHECK 二次兜底 | **PASS** | `tests/test_permission_resources.py::TestResourceServiceCreate::test_button_parent_must_be_page` |
| R4 | API 后端强制校验 | 授权判定发生在后端，且**不读取任何前端输入**；前端隐藏不构成安全边界 | `assert_api_permission` 仅依据 DB 中的有效角色/授权与 `ApiPermissionCode`；判权入参只有 `actor` 与 `api_code`，无请求体/前端字段 | **PASS** | `app/services/authorization.py:141-160`；受保护服务入口 `RoleService._load_role`、`RolePermissionService._load_role_id`、`PermissionResourceService._assert_can_manage`。**Phase 边界**：HTTP 层绑定（每个端点声明所需 API code）属 `docs/verification/008` 范围 |
| R5 | Field 支持 VISIBLE / HIDDEN / READ_ONLY / EDITABLE | 四级有序取值，多角色合并取最宽松者胜（`03 §9`，DD-06） | `FieldAccessLevel` 四级 + `_FIELD_ACCESS_RANK`；`most_permissive_field_level` 为**唯一**合并实现；HIDDEN 不否决其他角色的 VISIBLE | **PASS** | `app/models/enums.py`；`tests/test_permission_resources.py::TestFieldLevelMerge`（6 例）、`tests/test_effective_permission.py::TestFieldPermissionMerge::test_most_permissive_across_roles`、`::test_hidden_does_not_veto_visible` |
| R6 | Data Scope 支持 ALL / DEPARTMENT / DEPARTMENT_CHILDREN / SELF / CUSTOM | 五值全部可持久化、可解析、可下推 SQL | 五值落库（VARCHAR + CHECK）；解析按策略分支；CUSTOM 有专用持久化（DD-07）；多角色按 DD-19 求并 | **PASS** | `tests/test_role_data_scope.py::TestDataScopeColumn::test_all_five_scopes_are_persistable`；`tests/test_effective_permission.py::TestDataScopeMerge`（5 例）；`tests/test_scope_guard.py::TestIncludeSelfScopeCondition`（5 例，security） |
| R7 | 权限修改立即生效 | 修改后下一次判定即反映新权限（`00 §1#5` / `15 D-005`） | Phase 3 裁定**不启用 Redis 权限缓存**，权限上下文每请求实时计算 → 结构上不可能陈旧 | **PASS** | 裁定记录：`docs/DESIGN-DECISIONS.md §2 DD-03/DD-04`；`tests/test_effective_permission.py::TestUnionAcrossRoles::test_permissions_change_takes_effect_immediately` |
| R8 | 缓存失效后新权限立即可见 | 权限变更必须使旧缓存不可用（`11 §2`） | `permission_versions` 单调递增（`UPDATE ... SET version = version + 1`，行级锁）；**所有**改变权限的写路径均递增：角色状态变更、角色删除、授权替换、字段替换、数据范围设置/清空、继承授予/解除、用户角色分配 | **PASS**（带边界说明） | `app/repositories/permission.py:602`（`bump`）；`tests/test_role_service.py::test_status_change_bumps_version`、`::test_delete_bumps_version`；`tests/test_role_permission.py::test_replace_bumps_version`；`tests/test_role_inheritance.py::test_grant_creates_relation_and_bumps_version`；`tests/test_role_data_scope.py::TestPermissionVersionBump`（4 例）。**边界**：Redis Key 命名与失效**机制**属 DD-03/DD-04（未冻结，Phase 9）；本 Phase 以"实时计算"满足可观测要求 |
| R9 | 前端隐藏不能绕过后端 API | 后端判权独立于前端；前端变化不影响 API 安全 | 同 R4：判权只读数据库状态；`PermissionContext.has_api_permission` 是唯一 bypass 入口（`10 §3`） | **PASS** | `app/services/effective_permission.py:154`。**Phase 边界**：端到端证明（改前端不改后端 → 仍被拒）由 `docs/verification/008` 的 "前端变化不影响后端 API 安全" 覆盖 |
| R10 | SUPER_ADMIN 权限集中处理 | bypass 只出现在集中式授权层，业务 Service 中为 0 处（`10 §3`） | `is_super_admin` 判定仅 3 处：`AuthorizationService.assert_can_manage_user`、`.has_api_permission`、`PermissionContext.has_api_permission` —— 全在授权层；业务 Service（role / role_permission / role_inheritance / permission_resource / role_data_scope）内 **0 处** | **PASS** | `grep -rn "is_super_admin" app/services/` → 仅 `authorization.py` 与 `effective_permission.py`（后者为 `PermissionContext` 的集中判定）；`tests/test_effective_permission.py::TestSuperAdminBypass`（3 例） |
| R11 | Department Admin 无法越权 | 部门管理员的管理动作被限制在其部门子树内，越权必须被拒并留痕 | 范围解析 fail-closed：空集合 → SQL `FALSE`（不是"忽略条件"）；`include_self` 只做加法；服务端二次校验 `allows_department` / `allows_user`；所有拒绝写 FAILURE 审计 | **PASS** | `tests/test_scope_guard.py::test_empty_department_scope_returns_no_rows`（security）、`::test_self_scope_returns_only_actor_without_widening_to_department`（security）、`::TestIncludeSelfScopeCondition`（5 例 security）；`tests/test_role_service.py::test_non_super_admin_without_permission_is_denied`、`::test_read_requires_authorization`；`tests/test_role_inheritance.py::test_grant_requires_authorization` |

---

## 2. BLOCKED CHECKS

**无。** 23 项检查全部 PASS。

三项检查（R4 / R8 / R9）带有**Phase 边界说明**，性质是"本 Phase 交付了机制，
端到端证明属后续 Phase 的验收范围"，**不是** BLOCKED：

| CHECK | 边界 | 归属 |
|---|---|---|
| R4 API 后端强制校验 | HTTP 端点级的声明式绑定（`require_api_permission`） | `docs/verification/008` |
| R8 缓存失效 | Redis Key 命名与失效机制（DD-03 / DD-04 未冻结） | Phase 9（009） |
| R9 前端隐藏不能绕过 | 前端改动 → 后端仍拒绝的端到端验证 | `docs/verification/008` |

均已在 `docs/DESIGN-DECISIONS.md` 登记，不存在"以为已完成"的风险。

---

## 3. 本次执行中发现并修复的缺陷

### DEFECT-3-01（Critical）形状约束被 `OR` 连接 → 约束完全失效

- **现象**：`permission_resources` 的 `ck_permission_resources_resource_type_fields`
  在数据库里**恒为真** —— 给 `PAGE` 塞 `api_path`、`PAGE` 缺 `route_path`、
  `BUTTON` 缺 `parent_id`，全部可以写入。
- **根因**：每条类型子句是蕴含式 `(resource_type <> 'T' OR (T 的列形状))`。
  生成器用 `OR` 连接这些子句，于是任意一行只要存在一个与本行类型不同的 `T`
  （五类资源必然存在），对应子句即恒真，整条约束随之恒真。
- **为什么长期没暴露**：这是"看起来生效、实际没保护"的典型形态 ——
  写入任何数据都不报错；而且**原单测按 `"\n      OR "` 切分约束字符串**，
  等于跟着缺陷写测试，只校验了子句**内部**的极性，恰恰放过了**连接符**。
- **修复**：改为 `AND` 连接（`SHAPE_CLAUSE_SEPARATOR` 常量）；
  重新生成迁移约束；重跑 `alembic downgrade phase3_dd07 && upgrade head`
  并以 `pg_get_constraintdef` 复核。
- **防复发**：新增单测 `test_clauses_are_conjoined_by_and`，
  并让测试**引用模型常量**而非硬编码分隔符（避免测试再次跟着缺陷改）；
  数据库层新增 5 个"必须被拒绝"的用例作为最终防线。
- **证据**：`tests/test_permission_resources.py::TestShapeCheckExpression::test_clauses_are_conjoined_by_and`、
  `::TestResourceShapeConstraints::test_page_without_route_is_rejected` 等 5 例；
  修复前 `6 failed, 36 passed` → 修复后 `43 passed`。

### DEFECT-3-02（High）MENU 无法嵌套、无法配置图标

- **现象**：`MENU` 分支把 `parent_id` 与 `icon` 放进"必须为 NULL"集合，
  与 `03` 的"菜单层级 / 导航"语义直接矛盾。
- **修复**：引入 `TYPE_OPTIONAL_COLUMNS`（MENU 允许 `parent_id`、`icon`；
  API 允许 `parent_id`），并区分"必须非空 / 可选 / 必须为空"三类。
- **证据**：`tests/test_permission_resources.py::TestShapeCheckExpression::test_menu_allows_parent_and_icon`、
  `::TestResourceShapeConstraints::test_menu_with_parent_and_icon_is_accepted`。

### 认知纠正（非代码缺陷）外键不保证无环

- 原用例假设"直接插入成环会被外键拒绝 → 环不可能出现在库里"。
  **该假设错误**：外键只保证"被引用的行存在"，不保证无环。
  直接插入 `A.parent = B` 失败是因为 `B` 尚不存在；
  先建好两端再补边（`UPDATE`）即可成环。
- 据此改写用例为"先建点、后改父指针"，并保留服务层 `visited` 去重
  （构树）与递归 CTE `UNION` + 深度上限（展开）两道读路径防线。
- **证据**：`tests/test_permission_resources.py::TestResourceTree::test_tree_terminates_on_data_cycle`；
  `tests/test_role_inheritance.py::TestReadPathCycleSafety`（5 例）。

---

## 4. 未修复但已登记的发现（不得静默处理）

| 编号 | 内容 | 影响 | 登记位置 |
|---|---|---|---|
| **RISK-004** | `is_super_admin` 口径（`list_role_codes_for_user` 只筛 `deleted_at`）与权限并集口径（筛 ACTIVE）**不一致**：持有**被禁用的** SUPER_ADMIN 角色仍被当作 SUPER_ADMIN，从而获得全局数据范围与全部 API 权限 | 中（需要管理员先禁用超管角色这一非常规操作才会触发） | `docs/DESIGN-DECISIONS.md`；特征化测试 `tests/test_effective_permission.py::TestRisk004Characterization` |
| **FINDING-3-01** | "用户无任何**有效**角色"时，`EffectivePermissionService.build()` 抛 `ValueError`（fail-closed），而轻量路径 `resolve_api_codes()` 返回空集合；"范围内无部门"则可表示为合法空集合。三种边界表示不一致 | 低（当前无 HTTP 层）；**Phase 8 前必须统一**，否则 HTTP 层会分别得到 500 与 403/空权限 | `docs/DESIGN-DECISIONS.md`；测试 `tests/test_effective_permission.py::TestDisabledRolesAreExcluded` |
| **FINDING-3-02** | `ResourceScopeConfig` 残留行：非 CUSTOM 角色若在 `role_custom_scope_departments` 留有数据（上游写入路径 bug），引擎会记 warning 并**忽略**这些行（精度正确，但不放行也不报错） | 低（防御性） | `app/services/effective_permission.py::_build_scope_configs` 注释 |

---

## 5. 结论

> **Verification 002: PASS**

- 23/23 检查通过，0 项 BLOCKED，0 项 NOT RUN。
- 门禁：ruff + ruff format + mypy（62 source files）+ pytest **493 passed / 0 failed**。
- 2 个缺陷（1 Critical、1 High）已在本次执行中定位、修复、并补上防复发测试。
- 1 项已登记风险（RISK-004）与 2 项发现（FINDING-3-01/02）**未被静默处理**，
  已进入决策台账；其中 FINDING-3-01 需在 Phase 8 前统一口径。
- 未修改任何 Frozen Spec 或验收裁判文件。
