# Verification 001 — Organization / User

## 必须通过

- [ ] Department tree 可正确建立
- [ ] Department 支持逻辑删除
- [ ] User 支持创建/查询/修改
- [ ] User 支持 disable / enable
- [ ] User 删除为逻辑删除
- [ ] Department Admin 可创建其管理范围内用户
- [ ] Department Admin 不可创建越权范围用户
- [ ] Department Admin 数据范围为当前部门 + 所有子部门
- [ ] 多部门层级查询无越权
- [ ] 业务 ID 为 Snowflake BIGINT
- [ ] JSON ID 为字符串
- [ ] soft delete 不破坏查询
- [ ] 唯一约束考虑 deleted_at
