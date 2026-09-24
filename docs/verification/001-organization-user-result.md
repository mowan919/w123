# Verification 001 — Organization / User · 执行结果（补做）

| 项 | 值 |
|---|---|
| 验收依据 | `docs/verification/001-organization-user.md`（裁判文件，**未修改**） |
| 执行 Phase | `PHASES.md` Phase 1 — Organization / User |
| 执行时间 | 2026-09-24（**补做**，见下方"为什么是补做"） |
| 代码基线 | 实现提交于 `ec66678`；本次首次留痕的判定基于当前 `e0665fe` |
| 前置裁定 | 无新增阻塞项 |
| 数据库变化 | **无**（本次仅为判定留痕，未改动任何实现） |
| 执行方式 | `ruff check` + `ruff format --check` + `mypy` + `pytest` |
| 门禁结果 | ruff `All checks passed!` ｜ format `160 files already formatted` ｜ mypy `Success: no issues found in 77 source files` ｜ pytest **697 passed / 0 failed**（`EXIT=0`），详见 §4 |
| 结论 | **PASS**（13/13 检查通过；0 项 BLOCKED；0 项 NOT RUN） |

> 本文件是**执行结果记录**，不是验收裁判。
> `docs/verification/001-organization-user.md` 的 13 个检查项内容**一字未改**。

### 为什么这是"补做"，而不是现在才实现

Phase 1 的组织 / 用户管理**早已实现并提交**（`ec66678`
`feat: complete phase 2 organization and user management` ——
此处是 `docs/agent/PHASE-00N` 编号，对应 `PHASES.md` Phase 1）。
但是：**该 Phase 从未产出过结果文件**，13 项验收没有留下任何判定记录。

这是一个**流程缺口**，不是实现缺口：不能因为"代码已经写了"就把它记成 PASS
（`VERIFICATION_INDEX.md` 因此长期将其登记为 `NOT RUN（无结果文件）`）。
本次即是把这笔债补上——**重新按裁判书逐项判定**，并对每一给出可核对的证据。

判定对象是**当前代码**（`e0665fe`），而不是 `ec66678` 那一刻的快照。
理由是：代码在 Phase 2~4 中被合法演进过（例如授权从 INTERIM 实现替换为
`AuthorizationService` 集中式裁决、数据范围引入多角色求并 DD-19），
因此对当前代码做判定，比对一个已被取代的历史快照做判定更有意义。
若某次后续改动**退化**了 Phase 1 的能力，本次判定有责任把它暴露为 FAIL ——
本文件的判定即以此为准，结论为全部 PASS。

---

## 1. 逐项判定

| # | CHECK | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|---|
| 1 | Department tree 可正确建立 | 支持父子层级；树结构自身不得被破坏（自己当自己的父节点 / 形成环） | `Department.parent_id` 自引用外键；`parent_not_self` CHECK 约束在**数据库层**禁止自环。移动部门时服务层额外拒绝"移到自己的后代下"。注意：树不是无条件全树 —— `list_tree` 按操作者数据范围裁剪，"建立的树"对管理者而言始终是其可见子树 | **PASS** | `app/models/department.py:37`、`:42`、`:83`；`app/services/department.py:189`（`list_tree`）、`:375`（`_assert_parent_change_allowed`）；`tests/test_department_service.py::TestDepartmentTree`（4 例）、`::TestDepartmentUpdateAndDisable::test_cannot_move_department_under_own_descendant`、`::test_cannot_set_parent_to_self` |
| 2 | Department 支持逻辑删除 | 删除产生 `deleted_at` 标记，且不得破坏既有引用 | `SoftDeleteMixin.deleted_at`；`DepartmentService.delete` 置 `deleted_at`。删除前有两项前置守卫：存在**子部门**拒绝；子树内**仍有用户**拒绝。删除后该部门从树中消失，但其历史上的用户关联不因删除而被物理抹除 | **PASS** | `app/db/base.py:98`；`app/services/department.py:337`、`tests/test_department_service.py::TestDepartmentLogicalDelete`（6 例，含 `test_delete_refused_when_children_exist`、`test_delete_refused_when_users_exist_in_subtree`、`test_delete_succeeds_for_empty_leaf`、`test_deleted_department_disappears_from_tree`） |
| 3 | User 支持创建/查询/修改 | 具备 CRUD 路径，且读写都受数据范围约束 | 创建 `UserService.create`、分页查询 `list_users`、单查 `get`、修改 `update` 全部存在。更新接口**刻意不接受** `status` 与 `password` 字段（状态必须经 `disable`/`enable`、口令必须经改密/重置，避免"改资料顺手提权"） | **PASS** | `app/services/user.py:288`、`:251`、`:241`、`:350`；`tests/test_user_service.py::TestUserCreate`（9 例）、`::TestUserListScope`（10 例）、`::TestUserGetScope`（6 例）、`::TestUserUpdate`（7 例）、`::test_update_cannot_change_status` |
| 4 | User 支持 disable / enable | 支持禁用与恢复 | `disable` / `enable` 经同一私有方法 `_change_status`；两个方向都校验操作者数据范围，并在被拒时写 FAILURE 审计。禁用后用户**仍在列表中可见**（管理者需要看到被禁用者），但不能再登录 | **PASS** | `app/services/user.py:407`、`:416`、`:425`；`tests/test_user_service.py::TestUserStatus::test_disable_and_enable`、`::test_disabled_user_still_listed`、`::test_department_admin_cannot_disable_super_admin`、`::test_cannot_disable_last_super_admin` |
| 5 | User 删除为逻辑删除 | 用户删除不得物理抹除 | `delete` 同时置 `status=DISABLED` 与 `deleted_at`（双重表达：既不可登录、也不出现在常规查询结果中）。这是 `00 §1#8`"禁用 + 逻辑删除"的直接落地 | **PASS** | `app/services/user.py:455`；`tests/test_user_service.py::TestUserLogicalDelete::test_delete_sets_disabled_and_deleted_at`、`::test_deleted_user_is_not_readable`、`::test_cannot_delete_out_of_scope_user` |
| 6 | Department Admin 可创建其管理范围内用户 | 范围内创建必须成功 | `create` 经 `_assert_department_in_scope` 校验目标部门在范围内；范围管理者在其"当前部门 + 子部门"内创建成功。全局角色（SUPER_ADMIN）可创建无部门用户 | **PASS** | `app/services/user.py:288`、`:225`；`tests/test_user_service.py::TestUserCreate::test_department_admin_creates_user_in_scope`、`::test_super_admin_may_create_user_without_department` |
| 7 | Department Admin 不可创建越权范围用户 | 范围外创建必须被拒且留痕 | 目标部门在范围外 → 拒绝 + FAILURE 审计；范围管理者**不得**创建无部门用户（否则就绕出了自己的管辖范围）；范围管理者**不得**创建 SUPER_ADMIN（`10 §3` 提权防护） | **PASS** | 同上；`tests/test_user_service.py::TestUserCreate::test_department_admin_cannot_create_into_out_of_scope_department`、`::test_non_global_actor_cannot_create_user_without_department`、`::test_department_admin_cannot_create_super_admin` |
| 8 | Department Admin 数据范围为当前部门 + 所有子部门 | 默认范围必须是部门 + 子部门 | `DEPARTMENT_CHILDREN` 是角色的默认数据范围，解析结果含**自身 + 全部后代**（`test_department_children_includes_self_and_descendants`）。与 `DEPARTMENT`（仅本部门）是两个不同的取值，二者不混同 | **PASS** | `app/models/enums.py::RoleDataScope`；`tests/test_department_service.py::TestDataScopeResolution::test_department_children_includes_self_and_descendants`、`::test_department_scope_is_own_department_only`；`tests/test_role_data_scope.py`（24 例，覆盖 DD-07 的 CUSTOM 集合） |
| 9 | 多部门层级查询无越权 | 跨层级查询不得返回范围外数据 | 树查询与用户列表都把范围**下推到 SQL**（`10 §10` 禁止内存过滤）；越范围的部门查询被拒而非返回空集，避免"用 404/空结果掩盖越权" | **PASS** | `app/repositories/scope_filters.py::user_scope_condition`；`app/services/department.py:189`、`:222`；`tests/test_department_service.py::TestDepartmentTree::test_department_admin_sees_only_own_subtree`、`::test_get_out_of_scope_department_is_denied`；`tests/test_user_service.py::TestUserListScope::test_department_admin_sees_only_subtree`、`::test_out_of_scope_department_filter_yields_empty` |
| 10 | 业务 ID 为 Snowflake BIGINT | 主键为 BIGINT + Snowflake，禁止自增 / UUID | `PrimaryKeyMixin` 显式 `BigInteger` 且 `autoincrement=False`，`default=next_id`（Python 侧默认值，不产生 DDL）；生成逻辑在 `app/core/snowflake.py`。显式写 `autoincrement=False` 是为了杜绝"顺手用自增 ID"的实现偏差 | **PASS** | `app/db/base.py:51`–`:63`（含 Frozen 依据注释）；`app/core/snowflake.py`；`tests/test_api_contracts.py::TestSnowflakeIdSerialization::test_rejects_out_of_range_id`、`::test_rejects_boolean_id` |
| 11 | JSON ID 为字符串 | API JSON 中 BIGINT ID 序列化为字符串 | `SnowflakeId` 类型在 JSON 模式下输出字符串（避免 JS 的 2^53 精度丢失），Python 模式仍保留 `int`（内部逻辑不受影响）；输入侧接受数字字符串 | **PASS** | `app/schemas/types.py::SnowflakeId`；`tests/test_api_contracts.py::TestSnowflakeIdSerialization::test_response_id_is_json_string`、`::test_user_response_id_is_json_string`、`::test_page_response_ids_are_strings`、`::test_python_mode_keeps_int`、`::test_accepts_numeric_string_input` |
| 12 | soft delete 不破坏查询 | 逻辑删除后查询仍能正确工作，且不出现"幽灵行" | 常规查询一律排除 `deleted_at IS NOT NULL` 的行；删除后可从树 / 列表中消失；同时被释放的自然键可以被**重新使用**（这是"不破坏"的另一面：不会因为删了一行就让某个编码永久不可用） | **PASS** | `tests/test_user_service.py::TestUserListScope::test_deleted_users_are_excluded`、`::TestUserLogicalDelete::test_username_reusable_after_delete`；`tests/test_department_service.py::TestDepartmentCreate::test_code_can_be_reused_after_soft_delete`、`::TestDepartmentLogicalDelete::test_deleted_department_disappears_from_tree` |
| 13 | 唯一约束考虑 deleted_at | 唯一性只约束"存活"行，允许删除后复用 | `uq_admin_users_username_active` 与 `uq_departments_department_code_active` 均为 **partial unique index**（`WHERE deleted_at IS NULL`），而非普通 unique 约束。同一自然键在删除后可重建，重复的两条存活记录仍被拒 | **PASS** | `alembic/versions/20260923_2231_fdbaf573ca04_phase_2_organization_user_role_models.py:39`、`:74`；`app/models/department.py:84`、`app/models/user.py:119`；`tests/test_department_service.py::TestDepartmentCreate::test_duplicate_active_code_is_conflict`、`::test_code_can_be_reused_after_soft_delete`；`tests/test_user_service.py::TestUserCreate::test_duplicate_username_is_conflict` |

---

## 2. 裁判之外、本阶段必须自证的安全前提

裁判 001 未逐条列出下列三项，但它们是上表若干判定能成立的**前提**
（例如"不可创建越权范围用户"若不要求后端强制授权，就只剩前端约束）。

| 前提 | EXPECTED | ACTUAL | STATUS | EVIDENCE |
|---|---|---|---|---|
| 后端强制授权（`08 §10` / `5.1`） | 每个受保护端点必须经后端 API 权限校验，前端隐藏不得作为边界 | 组织 / 用户的读写统一经 `AuthorizationService`；SUPER_ADMIN 的 bypass **集中**在一处（`10 §3` 要求"禁止散落在 Controller 中"）。无权限 → 403 + FAILURE 审计 | **PASS** | `app/services/authorization.py`；`tests/test_authorization.py`；`tests/test_user_service.py::TestUserGetScope::test_read_out_of_scope_user_is_denied` |
| 敏感字段不返回（`10 §4`） | 响应中不得出现 password / password_hash | User 响应模型中没有任何口令字段；序列化后连属性名都不存在（不是置 None）。该项被**测试用例直接断言**而非依赖人眼检查 | **PASS** | `tests/test_api_contracts.py::TestPasswordNeverReturned`（3 例）、`::TestMutableFieldsAreRestricted::test_update_request_has_no_password_field` |
| 审计留痕（`10 §8`） | 关键操作必须可审计；拒绝也必须留痕 | 拒绝路径统一包在 `_denial_audited` 守卫内，避免"提前 raise 绕过审计"。成功事件记 capture 时会**脱敏**联系方式、**剔除**口令哈希 | **PASS** | `app/services/user.py:120`、`:147`、`:164`；`tests/test_denial_audit.py`；`tests/test_user_service.py::TestUserCreate::test_audit_snapshot_masks_contact_and_hides_password` |

---

## 3. BLOCKED CHECKS

**无。** 13 项全部有可核对证据，不存在：

- `BLOCKED_BY_ENVIRONMENT`（PostgreSQL / Redis 在本机直连远程实例，可用）；
- `BLOCKED_BY_DESIGN`（本 Phase 不涉及未冻结设计决策；数据范围合并规则 DD-19 与
  CUSTOM 数据范围的存储模型 DD-07 已在 Phase 3 裁定完成）。

> 注：与本 Phase 相邻的 **DD-21**（无有效角色用户的有效权限上下文表示）仍未冻结，
> 但它作用于 **Phase 8** 的动态权限输出，不影响本文件的任何一项判定。

---

## 4. 门禁

```
--- ruff check ---    All checks passed!
--- ruff format ---   160 files already formatted
--- mypy ---          Success: no issues found in 77 source files
--- pytest ---        697 passed in 608.57s (0:10:08)
EXIT=0
```

> 本次门禁在补做判定的**同一棵树**上执行，即"本次判定所依据的代码"本身通过了全套门禁。
>
> 说明：为避免 GBK 区域设置导致中文输出被破坏，此处直接用 venv 解释器依次执行
> `ruff check` / `ruff format --check` / `mypy` / `pytest`，
> 等价于 `scripts/dev.ps1 -Action verify` 的四个步骤。

本次为**补做**流程，除下列文件外未改动任何业务代码：

- 新增本结果文件 `docs/verification/001-organization-user-result.md`；
- `docs/verification/VERIFICATION_INDEX.md`：001 行由 `NOT RUN` 改为 `PASS`；
- `pyproject.toml`：见下方 FINDING；
- `alembic check` → `No new upgrade operations detected.`（无数据库变化）。

---

## 5. FINDING

### FINDING-1-01 `pyproject.toml` 未声明 `argon2-cffi`（**已修复**）

- **现象**：`app/core/security/password.py` 依赖 `argon2`（argon2id 口令哈希），
  该包在虚拟环境中存在（25.1.0），但**从未写入 `pyproject.toml` 的 `dependencies`**。
- **后果**：全新环境按 `pyproject.toml` 安装后，`import app.core.security.password`
  直接 `ModuleNotFoundError` —— 这是一个**只在干净部署时才爆**的缺陷，
  本地开发因为有 venv 残留而长期不可见（Spec `13 §3` 的部署风险）。
- **修复**：补 `argon2-cffi==25.1.0`（锁版，与既有依赖风格一致）。
- **为什么现在才发现**：此前所有验证都在已有 venv 内执行；
  本次逐条核对 Phase 1 的能力，顺带核对了"这些能力依赖什么"。

---

## 6. 结论

`docs/verification/001-organization-user.md` 的 **13 项全部 PASS**，0 项 BLOCKED。

本次为**补做**：补的是长期缺失的判定记录，同时也证明了
Phase 1 的能力在经历 Phase 2~4 的演进后**没有退化**。
`VERIFICATION_INDEX.md` 的 001 行已更新为 PASS。
