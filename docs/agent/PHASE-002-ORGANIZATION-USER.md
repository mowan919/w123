# PHASE-002 Organization / User

阅读：

- `docs/spec/02-组织与用户.md`
- `docs/spec/07-数据库设计.md`
- `docs/verification/001-organization-user.md`

实现：

- departments
- users
- status
- disable / enable
- logical delete
- department tree
- department admin scope

关键约束：

Department Admin = 当前部门 + 所有子部门。

完成后必须运行 Verification 001。
