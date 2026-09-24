# BLOCKED — NEED USER DECISION（Phase 3 / 角色与权限）

> 本文件**不是 Spec**，也不修改任何冻结结论。
> 它是 Agent 在 Phase 3 遇到的**设计阻塞点**的正式决策请求，
> 按 `AGENTS.md §4/§5` 与用户执行协议第七节的要求输出。
>
> 依据用户裁定"**由我起草，你审批**"，本文档包含 Agent 起草的**契约草案**。
> 审批通过后，Agent 将按草案实现，并回填 `docs/DESIGN-DECISIONS.md`。

---

## 裁定结果（2026-09-24，已解除阻塞）

| 编号 | 人类裁定 | 落地状态 |
|---|---|---|
| **CONFLICT-001 / DD-20** | **批准草案 A**（统一 `permission_resources` + 显式类型专属列 + CHECK + 独立 `menu_pages` + 统一 `role_permissions` + 8 个资源端点契约 + 声明式 API 绑定） | ✅ 已实现并验证（迁移 `phase3_dd20`）；资源 CRUD 的 HTTP 暴露属 `docs/verification/008` |
| **DD-05** | **批准草案 A**（邻接表 `role_inheritances` + 写入期环检测 + 递归 CTE `UNION` + 深度上限 32 + 被引用时拒绝删除） | ✅ 已实现并验证 |
| **DD-06** | **专用表 + 最宽松者胜**（`role_field_permissions`，`HIDDEN < READ_ONLY < VISIBLE < EDITABLE`） | ✅ 已实现并验证 |
| **DD-19** | **求并（最宽）**（可见集合求并；`ResolvedScope` 新增 `include_self`） | ✅ 已实现并验证 |

- 详细落地说明与证据见 `docs/DESIGN-DECISIONS.md §2`；
- 执行结果见 `docs/verification/002-permission-result.md`（**PASS**，23/23）；
- **CONFLICT-001 以"冻结契约"方式关闭**：未删除冲突条目、未弱化资源模型、
  未以临时 API 或硬编码权限资源绕过。

> 下文 §0~§7 为**决策请求原文**，保留以便追溯当时的阻塞状态与草案依据。

---

## 0. 阻塞总览（决策请求原文）

| 编号 | 主题 | 阻塞严重度 | 影响的验收项 |
|---|---|---|---|
| **CONFLICT-001 / DD-20** | 权限资源模型（PAGE/MENU/BUTTON/API/FIELD）与资源 CRUD 端点契约 | **PHASE-3-BLOCKER** | 002 §模型 Page/Menu/Button/API/Field；002 §规则"Page/Menu/Button 可配置""API 后端强制校验" |
| **DD-05** | 角色继承的存储与展开 SQL 细节 | **PHASE-3-BLOCKER** | 002 §模型"Role inheritance V1 生效"；`00 §1#3` / `15 D-003` 冻结项 |
| **DD-06** | Field Permission 最终表结构（含 4 级取值存储） | **PHASE-3-BLOCKER** | 002 §模型"Field Permission"；002 §规则"Field 支持 VISIBLE/HIDDEN/READ_ONLY/EDITABLE" |
| **DD-19** | 多角色数据范围合并规则 | **PHASE-3-BLOCKER** | 002 §模型"多 Role 权限取并集"（数据范围维度） |

**当前可交付且已交付**：DD-07（CUSTOM 数据范围持久化）。
**当前可交付但未做**：Role CRUD（`03 §2` 字段已冻结、`08 §7` 端点已给定、授权走已登记的 INTERIM 保守默认）——待本决策批准后与资源模型一并交付，避免二次返工。

---

## 1. 问题

Phase 3 要求实现完整 RBAC：

```text
User → Role → Role Inheritance → Page → Menu → Button → API → Field → Data Scope
```

但 Spec 只定义了**链的语义**，没有定义**链的载体**：

1. Spec `07 §5` 列出核心表 `roles` / `user_roles` / `role_inheritances` / `role_permissions`，
   并说"权限可进一步拆分为 page/menu/button/api/field/data_scope 关联表"。
   → 这是**授权（关联）**表，**不是资源定义表**。
2. **PAGE / MENU / BUTTON / API / FIELD 这五类"被授权的对象"存在哪张表、字段是什么、如何建树，
   Spec 全文没有任何定义。** 这就是 `CONFLICT-001`。
3. Spec `08 §7` 只给了 `/roles/{id}/permissions/{pages|menus|buttons|apis|fields}`，
   **没有给资源本身的 CRUD 端点**；而 `002-permission.md` 明确要求
   "Page 可配置 / Menu 可配置 / Button 可配置"。
   → 没有资源 CRUD，就没有"配置"，就没有动态权限闭环。
4. Spec `16 §34` 第 5/6/7 项明确把
   "Role inheritance 最终 SQL 存储细节""Field Permission 最终表结构"
   "CUSTOM Data Scope 最终存储模型"列为**技术设计待冻结项**。

---

## 2. 当前 Spec（原文摘录，不做解释性改写）

| 出处 | 原文 |
|---|---|
| `00 §1#3` | 角色继承：V1 支持 |
| `00 §1#4` | 一个 Menu 可关联多个 Page |
| `00 §1#5` | 权限变更：立即生效 |
| `00 §1#2` | 用户角色数量：支持多个角色，权限取并集 |
| `00 §3` | Field：VISIBLE / HIDDEN / READ_ONLY / EDITABLE；前端权限不能代替后端 API 权限 |
| `03 §4` | V1 支持角色继承。必须避免：循环继承 / 无限递归 / 重复权限 / 删除父角色导致隐式错误 |
| `03 §5` | Page 表示用户可以进入/查看的页面。页面必须可以由后台管理平台配置 |
| `03 §6` | Menu 表示导航结构。一个 Menu 可以关联多个 Page |
| `03 §9` | 最终字段策略需要由后端统一计算并向前端输出 |
| `03 §11` | 建议提供权限预览能力：用户当前有效权限 / 来源角色 / 继承链 / Data Scope / Field 权限 |
| `07 §5` | 核心：roles / user_roles / role_inheritances / role_permissions；权限可进一步拆分为 page/menu/button/api/field/data_scope 关联表 |
| `08 §7` | GET/POST `/roles`；PUT `/roles/{id}`；POST `/roles/{id}/delete`；GET `/roles/{id}/permissions`；PUT `/roles/{id}/permissions/{pages,menus,buttons,apis,fields}`；GET/PUT `/roles/{id}/data-scope` |
| `08 §10` | 每个受保护 API 必须经过后端 API Permission 校验。同时应用 Data Scope |
| `09 §2` | `GET /auth/permissions` 返回 pages / menus / buttons / APIs / fields / data scopes / permission version |
| `16 §34` | 5. Role inheritance 的最终 SQL 存储细节；6. Field Permission 的最终表结构；7. CUSTOM Data Scope 的最终存储模型 —— 属于技术设计决策，应在实现相应 Phase 前冻结 |

---

## 3. 代码现状

| 层 | 现状 |
|---|---|
| `roles` | ✅ 已建（`role_code` / `role_name` / `status` / `description` / `data_scope` + 逻辑删除感知唯一） |
| `user_roles` | ✅ 已建（复合主键 `(user_id, role_id)`，双 FK `RESTRICT`） |
| `role_custom_scope_departments` | ✅ 已建（DD-07 已冻结并实现，24 个测试） |
| `role_inheritances` | ❌ **未建**（DD-05 未冻结） |
| `role_permissions` | ❌ **未建**（依赖资源模型） |
| 资源定义表（5 类） | ❌ **未建**，Spec 未定义 |
| Role CRUD | ❌ 未实现（`08 §7` 端点已给定，可直接实现） |
| 授权引擎 / `PermissionContext` | ❌ 未实现 |
| HTTP 业务端点 | ❌ 全部未挂载（`app/api/v1/endpoints/` 目前只有 `health.py`；Phase 1/2 交付的是 Model/Repo/Service 层） |
| 集中式授权 | ⚠️ `AuthorizationService.assert_can_manage_roles` 为 **INTERIM：仅 SUPER_ADMIN**，已登记，Task 3.11 落地后必须替换 |

---

## 4. 为什么无法继续

- 没有资源定义表 → 无法实现"Page/Menu/Button 可配置"（`002` 规则项）；
- 没有资源表 → 没有 `resource_id` 可写入 `role_permissions` → 无法实现 `PUT /roles/{id}/permissions/pages`；
- 没有授权引擎 → 无法实现 `08 §10`"每个受保护 API 必须经过后端 API Permission 校验"；
- 因此 `002-permission.md` 中 5 个模型项 + 3 个规则项无法判定；
- 而"自行建一张资源表"属于**创建 Spec 未定义的业务模型**，
  违反 `AGENTS.md §14`"禁止未经确认修改冻结业务规则"与用户协议第七节。

**可选规避手段均已明确禁止**：临时 API、硬编码权限资源、绕过权限资源模型、删除 Conflict、改 Spec 让 Conflict 消失。

---

## 5. 契约草案（Agent 起草，待审批）

### 5.1 DD-20 / CONFLICT-001 —— 权限资源模型

#### 方案 A（**推荐**）：统一资源表 + 显式类型专属列 + 独立 Menu→Page 关联表 + 统一授权表

```text
permission_resources                     -- 五类资源统一载体
  id              BIGINT PK (Snowflake)
  resource_type   VARCHAR(16)  NOT NULL  CHECK IN ('PAGE','MENU','BUTTON','API','FIELD')
  resource_code   VARCHAR(128) NOT NULL  -- 业务唯一键，SUPER_ADMIN 式硬编码标识的来源
  resource_name   VARCHAR(128) NOT NULL
  parent_id       BIGINT NULL FK -> permission_resources.id RESTRICT   -- 树形自引用
  sort_order      INTEGER NOT NULL DEFAULT 0
  status          VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' CHECK IN ('ACTIVE','DISABLED')
  -- 类型专属列（可空；由 CHECK 保证"该类型必须非空"）
  route_path      VARCHAR(255) NULL   -- PAGE: 前端路由
  component_path  VARCHAR(255) NULL   -- PAGE: 组件
  icon            VARCHAR(64)  NULL   -- MENU
  api_method      VARCHAR(10)  NULL   -- API:  GET/POST/PUT/PATCH/DELETE
  api_path        VARCHAR(255) NULL   -- API:  /api/v1/admin/users  （支持 {id} 占位）
  field_key       VARCHAR(128) NULL   -- FIELD: 字段名
  owner_resource_id BIGINT NULL FK -> permission_resources.id RESTRICT -- FIELD 归属的 PAGE
  created_at / updated_at / deleted_at

  UNIQUE (resource_type, resource_code) WHERE deleted_at IS NULL
  INDEX  (parent_id) WHERE deleted_at IS NULL
  INDEX  (resource_type, status) WHERE deleted_at IS NULL
  CHECK  permission_resources_type_fields_ck   -- 按 resource_type 强制专属列组合

menu_pages                               -- 00 §1#4 一个 Menu 关联多个 Page（多对多）
  menu_id    BIGINT FK -> permission_resources.id RESTRICT
  page_id    BIGINT FK -> permission_resources.id RESTRICT
  created_at
  PK (menu_id, page_id)
  -- 由应用层保证 menu_id 指向 MENU、page_id 指向 PAGE（FK 无法表达类型）

role_permissions                         -- 07 §5 核心表（统一授权）
  role_id      BIGINT FK -> roles(id) RESTRICT
  resource_id  BIGINT FK -> permission_resources(id) RESTRICT
  created_at
  PK (role_id, resource_id)
```

**要点**
- **树的表达**：`parent_id` 自引用（邻接表）。
  `MENU → MENU`（导航层级）、`BUTTON → PAGE`、`FIELD → PAGE`、`API → PAGE`（或独立不挂树）。
- **Menu→Page 方向**：`Menu.page(s)` 是**导航入口**，`Page` 是**权限实体**（`09 §4`）。
  因此授权与判定只认 `Page`；`Menu` 仅决定导航可见性。
  这也解释了为何必须用独立表：`parent_id` 只能表达"单亲"，而一个 Page 可被多个 Menu 引用。
- **为什么不用 JSONB**：本项目既有风格（`native_enum=False` + `create_constraint=True`、
  CHECK 约束、`mypy --strict`）倾向强类型列 + CHECK；JSONB 会把约束退化到应用层。
- **为什么不拆 5 张表**：`07 §5` 已指定 `role_permissions` 为**单张**核心表，
  授权形态统一；拆表会导致 `/auth/permissions` 需要 5 次查询、新增资源类型要改表结构。

#### 方案 B：五张资源分表 + 五张授权关联表

- 优点：每表字段精确、CHECK 最强、无 NULL 列。
- 缺点：**与 `07 §5` 的单一 `role_permissions` 冲突**；CRUD/授权/查询各 5 套；
  新增资源类型需改表；判权时需 5 次 JOIN。
- 结论：**不推荐**（与冻结的 `07 §5` 不一致）。

#### 方案 C：统一资源表 + JSONB `metadata` 承载类型专属字段

- 优点：CRUD 最简，类型扩展零成本。
- 缺点：类型专属约束全部退到应用层；`api_method`/`api_path` 这类**安全关键字段**
  无法用数据库约束兜底；查询与索引不友好。
- 结论：**不推荐**（安全关键字段不宜放入非结构化列）。

#### 5.1.1 资源 CRUD 端点（`08 §7` 缺席部分，草案新增）

```text
GET    /api/v1/admin/permission-resources?resourceType=&parentId=&keyword=&status=&pageNum=&pageSize=
POST   /api/v1/admin/permission-resources
GET    /api/v1/admin/permission-resources/{id}
PUT    /api/v1/admin/permission-resources/{id}
POST   /api/v1/admin/permission-resources/{id}/delete        -- 逻辑删除（引用检查）
GET    /api/v1/admin/permission-resources/tree?resourceType=MENU
GET    /api/v1/admin/permission-resources/{id}/pages         -- 仅 MENU：读取关联 Page
PUT    /api/v1/admin/permission-resources/{id}/pages         -- 仅 MENU：整体替换关联 Page
```

`08 §7` 既有角色授权端点保持不变，请求体统一为**整体替换**语义：

```json
PUT /api/v1/admin/roles/{id}/permissions/pages
{ "resourceIds": ["1001", "1002"] }
```

- **整体替换**（而非增量 add/remove）理由：PUT 语义幂等、before/after 可直接落审计、
  与既有 `replace_user_roles` / `replace_custom_scope_departments` 保持一致。
- 对 `fields` 端点，请求体改为携带等级（见 DD-06）：
  ```json
  PUT /api/v1/admin/roles/{id}/permissions/fields
  { "fields": [ { "resourceId": "2001", "accessLevel": "READ_ONLY" } ] }
  ```

#### 5.1.2 `resource_code` 唯一性范围

`UNIQUE (resource_type, resource_code) WHERE deleted_at IS NULL`

- **按类型唯一**（而非全局唯一）：`PAGE` 与 `BUTTON` 允许同名 code
  （如 `user:list` 既是页面也是按钮语义），强行全局唯一会制造无谓耦合。
- **逻辑删除感知**：删除后可重建同 code（`00 §6` / `07 §9`）。

#### 5.1.3 API 权限的绑定方式

**草案：声明式绑定**（推荐）——受保护路由通过依赖声明其 API `resource_code`：

```python
@router.post("/users", dependencies=[Depends(require_api_permission("USER_CREATE"))])
```

- 理由：路径模式匹配（`api_method` + `api_path` 正则）在 `{id}`、尾斜杠、方法覆盖场景下
  容易漏判；**漏判即越权**。声明式绑定在"路由注册期"就固定，漏声明的路由
  可被启动期自检扫描出来（`009-hardening` 阶段加"未声明授权的路由 = 启动警告"）。
- `api_method` / `api_path` 仍落库，用于**资源台账**与前端展示（"该 API 被哪些角色授权"），
  但不作为**判权主键**。

---

### 5.2 DD-05 —— 角色继承的存储与展开

#### 方案 A（**推荐**）：邻接表 + 应用层环检测 + 递归 CTE(UNION) 展开 + 深度上限

```text
role_inheritances                        -- 07 §5 已点名的核心表
  parent_role_id  BIGINT FK -> roles(id) RESTRICT   -- 被继承者（提供权限）
  child_role_id   BIGINT FK -> roles(id) RESTRICT   -- 继承者（获得权限）
  created_at
  PK (parent_role_id, child_role_id)
  CHECK parent_role_id <> child_role_id              -- 禁止自环
  INDEX (child_role_id)
```

**语义**：`child` 继承 `parent` 的权限；有效权限 = 直接角色 ∪ 其全部祖先角色。

**展开**：与 `app/repositories/department.py` 的部门子树**同一模式**：

```sql
WITH RECURSIVE chain(role_id) AS (
    SELECT :role_id
    UNION                                -- 注意是 UNION 不是 UNION ALL：
    SELECT ri.parent_role_id             -- 天然去重 + 环路时自动收敛，不会无限递归
      FROM role_inheritances ri
      JOIN chain c ON ri.child_role_id = c.role_id
)
SELECT role_id FROM chain;
```

- `UNION`（而非 `UNION ALL`）是**环路安全的第一道防线**（`03 §4`"无限递归"）。
- **第二道防线**：写入时环检测 —— 授予
  `parent←child` 前，先展开 `parent` 的**祖先集合**，若包含 `child` 则拒绝（409）。
- **第三道防线**：展开时深度上限（草案取 32），超限 fail-closed 抛错并记 FAILURE 审计。
- **删除父角色**（`03 §4`"删除父角色导致隐式错误"）：
  存在任何 `role_inheritances` 引用（作为 parent 或 child）时**拒绝逻辑删除**（409），
  要求先解除继承关系 —— 拒绝优于隐式级联删除（级联会让子角色静默掉权限）。

#### 方案 B：闭包表 `role_inheritance_closure(ancestor_id, descendant_id, depth)`

- 优点：查询 O(1) 无需递归；祖先集合直接可用。
- 缺点：写入需维护闭包（插入 N 行）；与"应用层环检测"耦合仍存在；
  与既有部门子树实现模式不一致（项目已有递归 CTE 先例，**模式一致性**本身有价值）。
- 结论：**不推荐**（Phase 3 规模下无性能收益，复杂度显著上升）。

#### 方案 C：保持未冻结 → 不实现继承

- 后果：`00 §1#3` / `15 D-003` 冻结项**无实现**；
  `002-permission.md` "Role inheritance V1 生效" **FAIL**；
  `PHASE-003` 完成条件 "Role Inheritance / Circular Inheritance Protection" **FAIL**；
  权限并集**不含继承链**。
- 结论：**会让 Phase 3 无法 PASS**，故不作为推荐；如选择此项，Phase 3 只能以 BLOCKED 收尾。

---

### 5.3 DD-06 —— Field Permission 表结构

#### 方案 A（**推荐**）：专用 `role_field_permissions` 表，`access_level` 四值

```text
role_field_permissions
  role_id       BIGINT FK -> roles(id) RESTRICT
  field_id      BIGINT FK -> permission_resources(id) RESTRICT   -- resource_type='FIELD'
  access_level  VARCHAR(16) NOT NULL CHECK IN ('VISIBLE','HIDDEN','READ_ONLY','EDITABLE')
  created_at
  PK (role_id, field_id)
```

**为什么不能复用 `role_permissions`**：`00 §3` 的 Field 权限是**四级有序取值**，
不是"有/无"二元；用二元表承载会丢失等级信息（等于把 HIDDEN 与 EDITABLE 视为相同）。

**多角色合并**（同一字段被多角色授予不同等级）：
草案取**最宽松者胜**（permissive union），
序：`HIDDEN < READ_ONLY < VISIBLE < EDITABLE`。
- 理由：`00 §1#2` 冻结"权限取并集"，等级合并沿用同一方向，语义自洽（可解释性优先）。
- **必须注意**：该方向下 `HIDDEN` 无法覆盖其他角色的 `VISIBLE`
  （即"一个角色隐藏"不足以对全局隐藏）。若业务期望"HIDDEN 是硬性否决"，
  必须改选**最严格者胜**或"HIDDEN 一票否决"混合规则。

#### 方案 B：复用 `role_permissions` + 新增 `access_level` 可空列

- 优点：单表。缺点：非 FIELD 行该列恒为 NULL，语义混杂；
  CHECK 需写"仅当 resource_type=FIELD 时非空"，而该表拿不到 `resource_type`（跨表约束）；
  最终仍需 JOIN 资源表才能校验。结论：**不推荐**。

#### 方案 C：等级存 JSONB 于 `role_permissions.access_level_json`

- 缺点：等级取值失去 CHECK 约束。结论：**不推荐**。

---

### 5.4 DD-19 —— 多角色数据范围合并规则

Spec 只冻结了"权限取并集"（`00 §1#2`），**未规定数据范围如何合并**。
每个角色各带一个 `data_scope`，多角色用户的实际可见边界 Spec 未定义。

#### 方案 A（**推荐**）：可见集合求并（最宽）

- `ALL` ∪ 任意 = `ALL`（即持有一个 ALL 角色即全局可见，符合该角色语义）。
- `DEPARTMENT_CHILDREN(d1)` ∪ `CUSTOM{d2,d3}` = `{d1 及后代} ∪ {d2,d3}`。
- `SELF` ∪ 其他 = 其他可见集合 **外加 actor 本人**。
- 与 `00 §1#2`"权限取并集"方向一致，可解释性最好。
- **实现影响**：`ResolvedScope` 需新增 `include_self: bool`
  （现有模型只有 `restrict_to_actor`，是"仅本人"语义，**无法表达"部门集合 ∪ 本人"**）。
  这是对已交付 Phase 2 组件的**扩展**（新增字段，不改现有语义），需要一并改动 + 回归测试。

#### 方案 B：求交（最窄）

- 最保守，无越权风险。但多角色用户同时持 `SELF` + `DEPARTMENT_CHILDREN` 时
  可见范围退化为"本人在本部门" —— 大量正常场景会"看到空白页"，
  且与"并集"的方向**相反**，难以向业务解释。

#### 方案 C：继续保持未冻结（Phase 3 只支持单角色数据范围）

- 后果：`002` "多 Role 权限取并集"在数据范围维度**无法验证**；
  多角色用户的范围解析仍取"单一 `CurrentActor.data_scope`"（现有 INTERIM 行为）。
- 结论：会让 Phase 3 该验收项降级为 BLOCKED。

---

## 6. 每个方案的影响对照

| 决策 | 方案 A（推荐） | 方案 B | 方案 C |
|---|---|---|---|
| DD-20 资源模型 | 新增 `permission_resources` + `menu_pages` + `role_permissions`；1 张表承载 5 类；新增 8 个资源端点 | 5 资源表 + 5 授权表；**与 07 §5 冲突**；端点 40+ | JSONB 承载类型字段；安全关键字段失去 DB 约束 |
| DD-05 继承 | 新增 `role_inheritances`；递归 CTE(UNION)；三层环防护；删除引用拒绝 | 闭包表；写入维护成本高；模式与既有实现不一致 | 不实现 → 002 该项 FAIL，Phase 3 无法 PASS |
| DD-06 字段权限 | 新增 `role_field_permissions`（4 值 CHECK）；最宽松者胜 | 单表 + 可空列；跨表 CHECK 不可表达 | JSONB；失去 CHECK |
| DD-19 范围合并 | 求并（最宽）；`ResolvedScope` 扩展 `include_self` | 求交（最窄）；正常场景大面积空白 | 不合并 → 该项 BLOCKED |

**统一影响**（选择 A 方案时）：

- 数据库：新增 4 张表（`permission_resources`、`menu_pages`、`role_permissions`、
  `role_inheritances`、`role_field_permissions`，共 5 张）+ 1 个 Alembic 迁移；
- API：新增 8 个资源端点（`08 §7` 之外的空白），既有 `08 §7` 角色授权端点落地；
- 代码：`AuthorizationService` 从 INTERIM 升级为基于 API Permission 的判定，
  移除 `assert_can_manage_roles` 的 INTERIM 标注；
- 测试：资源 CRUD、继承环、权限并集、字段等级合并、范围合并、403 越权、审计。

---

## 7. 需要你决定的具体问题

1. **DD-20 / CONFLICT-001**：是否批准 **5.1 方案 A**（统一 `permission_resources` + `menu_pages`
   + `role_permissions` + 8 个资源端点 + 声明式 API 绑定 + 按类型逻辑删除感知唯一）？
2. **DD-05**：是否批准 **5.2 方案 A**（`role_inheritances` 邻接表 + 递归 CTE UNION
   + 写入期环检测 + 深度上限 32 + 删除引用拒绝）？
3. **DD-06**：是否批准 **5.3 方案 A**（专用 `role_field_permissions`），
   以及 `HIDDEN` 是否为**硬性否决**（一票否决 / 最严格者胜 / 最宽松者胜）？
4. **DD-19**：是否批准 **5.4 方案 A**（可见集合求并 + `ResolvedScope` 新增 `include_self`）？

审批后 Agent 将：
1. 回填 `docs/DESIGN-DECISIONS.md`（DD-05/06/19/20 状态 → 已冻结）；
2. 按 `PHASE-003` Task 3.3 / 3.5 / 3.6~3.9 / 3.11 / 3.13 / 3.14~3.16 实现；
3. 运行完整 Verification 002；
4. 输出 `PHASE 3 STATUS: READY FOR VERIFICATION` 并停止（不进入下一 Phase，除非整体流程允许）。

---

## 8. 附：本次不动摇的约束

- 不创建临时 API、不硬编码权限资源、不绕过权限资源模型；
- 不删除 `CONFLICT-001`、不改 Spec 让其消失；
- 不改动任何已冻结结论（`00` / `15`）；
- 所有新增表：BIGINT + Snowflake 主键、API JSON 序列化为字符串、UTC 时间、snake_case、逻辑删除感知唯一索引；
- 所有权限判定在**后端**执行，前端隐藏不作为安全边界。
