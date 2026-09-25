# Verification 008 — Dynamic Permission 执行结果

- 裁判：`docs/verification/008-dynamic-permission.md`（11 项）
- 阶段：`PHASES.md` Phase 8 — Dynamic Frontend Permission Contract
- 日期：2026-09-25
- 提交：`feat: complete phase 8 dynamic frontend permission contract`

| 项 | 值 |
|---|---|
| 结论 | **PASS**（11/11 检查通过；0 项 BLOCKED；0 项 NOT RUN） |
| 门禁 | ruff `All checks passed!` / format `209 files already formatted` / mypy `Success: no issues found in 103 source files` / alembic `No new upgrade operations detected.` / pytest **`1156 passed`** |
| 增量 | Phase 7 结束为 1088 例 → 现 **1156 例（+68）**，零告警 |

---

## 1. 逐项判定

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 1 | 后端可返回当前用户**页面**权限 | `GET /auth/permissions` 的 `pages[]` 携带可动态注册路由所需的全部信息 | `pages[].{id,code,route_path,component_path,parent_id,sort_order,status}`；页面是被**授权**后才出现的（`role_permissions` ∩ ACTIVE ∩ 未删除） | **PASS** | `app/services/permission_contract.py`；`tests/test_dynamic_permission_api.py::TestContractContent::test_pages_carry_route_and_component`；`tests/test_permission_contract.py::TestBinaryPermissions::test_role_grants_are_rendered_with_metadata` |
| 2 | 后端可返回**菜单**权限 | `menus[]` 含层级、图标，且只指向**已授权**页面 | `menus[].{id,code,title,icon,parent_id,sort_order,page_ids}`；`page_ids = 菜单关联 Page ∩ 用户已授权 Page`（求交，非原始关联） | **PASS** | `test_menus_expose_hierarchy_icon_and_accessible_pages`；`tests/test_permission_contract.py::test_menu_pages_are_intersected_with_granted_pages` |
| 3 | 后端可返回**按钮**权限 | `buttons[]` 含所属页面，前端据此显隐 | `buttons[].{id,code,owner_resource_id}`；`owner_resource_id` 指向其 Page | **PASS** | `test_buttons_are_attached_to_their_page`；`tests/test_permission_contract.py::TestFieldsAndScope::test_field_policies_carry_owner_page` |
| 4 | 后端可返回 **API** 权限 | `apis[]` 与实际后端判权**分开**验证；契约只作台账，不构成授权 | `apis[].{id,code,api_method,api_path}`；真实判权仍走 `AuthorizationService.assert_api_permission`，不读契约 | **PASS** | `test_apis_carry_method_and_path`；`TestFrontendCannotAffectBackendAuthorization` |
| 5 | 后端可返回**字段**权限 | `fields[]` 含四级取值 + 所属页面（DD-06 最宽松者胜已合并） | `fields[].{resource_id,field_key,access_level,owner_resource_id}`；`access_level ∈ {HIDDEN, READ_ONLY, EDITABLE, VISIBLE}` | **PASS** | `test_fields_carry_level_and_owner`；`tests/test_permission_contract.py::test_field_levels_are_merged_most_permissive_wins` |
| 6 | 后端可返回 **data scope** | 返回**已解析**的范围，而非角色上的原始配置值 | `data_scope.{policy, department_ids, include_self}`；`department_ids` 三态：`null`=不限制 / `[]`=全拒 / 非空=允许集合；`DEPARTMENT_CHILDREN` 已展开为含后代 | **PASS** | `test_data_scope_is_resolved_not_raw`；`tests/test_permission_contract.py::test_data_scope_is_resolved_and_merged` |
| 7 | 页面可由后台配置 | 页面资源可经 API 增改查删，不需改代码 | `POST/GET/PUT/DELETE /admin/permission-resources*` 全部可用；`PAGE` 缺 `route_path` → 422；跨类型形状违规 → 422；被引用时删除 → 409 | **PASS** | `tests/test_permission_resource_api.py::TestPageCrud::test_page_can_be_created_read_updated_and_deleted`、`::test_page_without_route_is_rejected`、`::test_shape_violation_across_types_is_rejected`、`::test_delete_is_rejected_while_referenced` |
| 8 | Menu 可关联多个 Page | 一个菜单可挂多个页面；非 PAGE 不可挂；非 MENU 不可被挂 | `GET/PUT /admin/permission-resources/{id}/pages`；多挂成功；挂非 PAGE → 422；给非 MENU 挂页 → 400 | **PASS** | `test_menu_can_link_multiple_pages`、`::test_non_page_resource_cannot_be_linked`、`::test_pages_of_non_menu_resource_is_rejected` |
| 9 | 前端可根据后端配置**动态生成** route/menu | 消费方只凭响应即可构造路由表与菜单树，无需硬编码权限常量 | 测试内实现**独立消费者**（`build_route_table` / `build_menu_tree` / `attach_buttons`），只读响应、不读库、不引用任何 Python 权限常量；缺 `route_path`/`component_path`/`parent_id`/`page_ids` 任一项消费者即构造失败 | **PASS** | `TestDynamicGeneration::test_route_table_can_be_generated_from_the_contract`、`::test_menu_tree_is_pruned_by_the_consumer`、`::test_buttons_and_fields_are_wired_to_their_pages`、`::test_nested_menus_are_rendered_as_a_tree` |
| 10 | 前端变化**不影响**后端 API 安全 | 有页面/按钮 ≠ 有接口；有接口 ≠ 有页面 | 配对用例：仅授 `PAGE` 后调受保护接口 → **403/403001**；仅授 `API` 而无页面 → 契约 `pages=[]` 但接口 **200** | **PASS** | `TestFrontendCannotAffectBackendAuthorization::test_interface_permissions_do_not_grant_api_access`、`::test_api_authorization_works_without_any_interface_permission`；`tests/test_permission_resource_api.py::TestAccessControl::test_page_permission_does_not_grant_api_authorization` |
| 11 | 权限变更**立即生效** | 变更无需重登录、无 stale | **同一令牌**在授权变更前后两次读契约，结果随变更变化；禁用资源、改数据范围同样即时；实现上**不使用任何缓存** | **PASS** | `tests/test_role_permission_api.py::TestImmediateEffect::test_grant_change_is_visible_without_relogin`、`::test_disabling_a_resource_takes_effect_immediately`、`::test_data_scope_change_is_visible_in_contract` |

---

## 2. 裁判之外必须自证的前提

裁判 11 项只描述"能返回什么"。以下 6 项是"返回得对不对"的必要条件，
不自证则 PASS 可能建立在错误前提上：

| 项 | 自证内容 | 证据 |
|---|---|---|
| A | **端点存在性**：`08 §3` 的 `/auth/permissions` 与 DD-20 要求的资源 CRUD 端点真的挂上了，且路径逐条可核 | `tests/test_dynamic_permission_api.py::TestRouteSurface::test_permissions_endpoint_is_mounted_in_the_auth_domain`、`tests/test_permission_resource_api.py::TestRouteSurface::test_permission_resource_paths_match_the_frozen_contract` |
| B | **读路径不越权**：契约端点只返回**本人**，不接受任何"目标用户"入参 | `test_contract_endpoint_does_not_accept_a_target_user`（`userId` / `user_id` / `username` 三种入参一律被忽略或拒绝） |
| C | **认证前置**：匿名 401/401001；强制改密状态 403；无 `ROLE_MANAGE` 调角色授权端点 403/403001 | `TestAccessControl` 三文件各自覆盖；`test_forced_password_change_state_is_rejected_with_403` |
| D | **不泄漏敏感物**：响应体不含 `password` / `password_hash` / `access_token` / `refresh_token` / `secret` / 真实口令字面量 | `test_no_sensitive_material_leaks_into_the_contract`（对 `response.text` 逐字节断言） |
| E | **ID 为字符串**：契约中全部业务 ID 序列化为字符串（`07 §2` / `00 §6`） | `app/schemas/types.py::SnowflakeId`；`tests/test_dynamic_permission_api.py` 的消费者按键取值即依赖此约定 |
| F | **SUPER_ADMIN 一致性**：超管契约返回全部 ACTIVE 资源（与 `10 §3` 集中式 bypass 一致），但**字段权限不做 bypass** | `tests/test_permission_contract.py::TestSuperAdmin::test_super_admin_receives_all_active_resources`、`::test_super_admin_field_policies_are_not_bypassed`、`::test_super_admin_data_scope_is_unrestricted` |

---

## 3. BLOCKED CHECKS

**无。**

既无 `BLOCKED_BY_ENVIRONMENT`（PostgreSQL / Redis 本机直连远程实例，可用），
也无 `BLOCKED_BY_DESIGN`：

- DD-20 / CONFLICT-001 已于 Phase 3 以"冻结契约"方式**关闭**，
  且明确"资源 CRUD 的 HTTP 端点暴露属 008 交付范围" —— 本 Phase 已交付。
- **DD-21**（无有效角色用户的权限上下文表示）虽仍为未冻结项，
  但本 Phase **未做任何需要裁定的行为变更**：`build()` 默认行为完全不变
  （仍 fail-closed 抛错），只对新增读路径启用拒绝型上下文。
  详见 `docs/DESIGN-DECISIONS.md §15.5`，**待人类追认**。

### 本 Phase 登记项

| 编号 | 内容 | 状态 |
|---|---|---|
| INTERIM-8-01 | 资源端点路径 `/admin/permission-resources*`（`08 §3–§9` 未列出，取与既有复数资源一致命名） | 已登记 |
| INTERIM-8-02 | `GET /auth/permissions` 不写审计（同 INTERIM-7-05 取向） | 已登记 |
| INTERIM-8-03 | 契约不裁剪空菜单（渲染策略归前端） | 已登记 |
| INTERIM-8-04 | 资源树缺 `resourceType` → 400 而非空树 | 已登记 |
| INTERIM-8-05 | 响应 `snake_case` / 请求 camelCase | 已登记 |
| INTERIM-8-06 | 六条显式路由而非 `/permissions/{kind}` | 已登记 |
| JUDGMENT-8-01 | SUPER_ADMIN 契约表达（全部资源；字段权限**不** bypass） | 已登记 |
| JUDGMENT-8-02 | `/auth/permissions` 不需 API 权限位，但要求已认证且用严格依赖 | 已登记 |
| **FINDING-8-01** | 组织实体（users / departments / roles）CRUD 的 **HTTP 面至今未交付** | **未关闭 → Phase 10 前必须关闭** |

> **FINDING-8-01 说明**：`08 §4/§6/§7` 冻结了这些端点清单，但仓库只有服务层。
> 根因是 `001` / `002` 裁判项全是服务层判定，不含端点存在性，
> 因此 Phase 1 / 2 PASS 时不会暴露。本 Phase **不越界补实现**
> （组织实体 CRUD 属 Phase 1 / 2，越界会打乱阶段边界），
> 但它在 Phase 10「Functional: Organization / User / Role」之前必须关闭，
> 否则"后端全部做完"不成立。

---

## 4. 交付清单

**新增**

- `app/schemas/permission_contract.py` — 契约响应 DTO（七段：pages / menus / buttons / apis / fields / data_scope / permission_version）
- `app/services/permission_contract.py` — 把 `PermissionContext` 投影为前端可消费契约
- `app/api/v1/endpoints/permission_resources.py` — DD-20 要求的资源 CRUD 端点（列表 / 创建 / 详情 / 修改 / 删除 / 树 / 读取关联页面 / 替换关联页面）
- `app/api/v1/endpoints/role_permissions.py` — `08 §7` 的角色授权与数据范围端点
- `tests/test_permission_contract.py`、`tests/test_permission_resource_api.py`、`tests/test_role_permission_api.py`、`tests/test_dynamic_permission_api.py`

**修改**

- `app/api/deps.py` — 新增 `require_api_permission()`（DD-20 §5.1.3 冻结的声明式绑定）及四个服务依赖提供者
- `app/api/v1/endpoints/auth.py` — 新增 `GET /auth/permissions`
- `app/api/v1/router.py` — 挂载两条新路由
- `app/services/effective_permission.py` — `build(allow_empty_roles=...)`（默认行为不变）
- `app/repositories/permission.py` — 补 `list_all_live` / `list_menu_page_map` 批量读方法
- `tests/test_auth_api.py` — 原"/auth/permissions 不得存在"的反向断言改为与 `08 §3` 逐条相等的正向钉住

**迁移**：本 Phase **无**新增迁移（`alembic check` 确认 `No new upgrade operations detected.`）。

---

## 5. 门禁与复现

```powershell
.\.venv\Scripts\ruff.exe check .            # All checks passed!
.\.venv\Scripts\ruff.exe format --check .   # 209 files already formatted
.\.venv\Scripts\mypy.exe                    # Success: no issues found in 103 source files
.\.venv\Scripts\alembic.exe check           # No new upgrade operations detected.
.\.venv\Scripts\python.exe -m pytest -q     # 1156 passed in 1269.37s
```

---

## 6. 本 Phase 发现并修复的缺陷

| # | 缺陷 | 后果 | 修复 |
|---|---|---|---|
| 1 | 无有效角色用户的 `data_scope.department_ids` 曾返回 `null` | `null` 语义是"部门维度**不限制**"，等于把"全拒"表达成"全放行" —— 契约层面的 **fail-open**，且 JSON 里 `null` 与 `[]` 都"看起来像空" | `policy=null` 时 `department_ids` 恒为 `[]`；三态语义写入 DTO docstring 并由测试钉住 |
| 2 | `/permission-resources/tree` 若注册在 `/{resource_id}` 之后 | `tree` 被当 ID 交给 `int` 解析 → **422 而非 200**；两个装饰器各自都"正确" | 树路由声明在前，并由**真实请求**钉住（只比对注册顺序不足以证明） |

---

## 7. 结论

`docs/verification/008-dynamic-permission.md` 的 **11 项全部 PASS**，0 项 BLOCKED。

一处交付缺口（FINDING-8-01）**未被静默处理**，已登记并指定关闭时点。
