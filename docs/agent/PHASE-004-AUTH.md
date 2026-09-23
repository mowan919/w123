# PHASE-004 Authentication

阅读：

- `docs/spec/04-认证MFA与Session.md`
- `docs/spec/10-安全设计.md`
- `docs/verification/003-authentication.md`

实现：

- login
- password policy
- failed attempts
- lockout
- password reset
- forced password change
- logout
- refresh
- me

密码规则：

- min 12
- upper
- lower
- digit
- special
- last 5 cannot repeat
- 90 days
- 5 consecutive failures → 30 minutes lock

完成后必须运行 Verification 003。
