# VCTN Frontend Spec

本目录定义 VCTN 后台管理平台前端完整 Spec。

技术栈冻结：
- Vue 3
- TypeScript
- Vite
- Vue Router
- Pinia

核心原则：
1. 后端是权限最终裁决者。
2. 前端负责权限驱动的路由、菜单、按钮、字段展示与交互。
3. 前端权限控制不能替代后端 API Authorization。
4. BIGINT 业务 ID 在 TypeScript 中统一使用 string。
5. 未冻结的技术决策不得由 Coding Agent 擅自决定。
