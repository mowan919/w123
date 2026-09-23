# PHASE-008 Dynamic Permission

阅读：

- `docs/spec/09-前端动态权限.md`
- `docs/spec/03-角色与权限.md`
- `docs/verification/008-dynamic-permission.md`

实现后端权限输出协议，使前端能够动态生成：

- route/page
- menu
- button
- field behavior

Menu 可以关联多个 Page。

后端 API authorization 仍然是最终安全边界。
