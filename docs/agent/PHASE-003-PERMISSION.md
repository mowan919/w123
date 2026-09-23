# PHASE-003 Permission

阅读：

- `docs/spec/03-角色与权限.md`
- `docs/spec/09-前端动态权限.md`
- `docs/spec/10-安全设计.md`
- `docs/verification/002-permission.md`

实现：

- multi-role
- role inheritance
- page
- menu
- button
- API
- field
- data scope
- effective permission engine

关键约束：

```text
User
 ↓
Role
 ↓
Role Inheritance
 ↓
Page
 ↓
Menu
 ↓
Button
 ↓
API
 ↓
Field
 ↓
Data Scope
```

多角色权限取并集。

权限修改立即生效。

完成后必须运行 Verification 002。
