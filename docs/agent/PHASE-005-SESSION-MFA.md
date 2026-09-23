# PHASE-005 Session / MFA

阅读：

- `docs/spec/04-认证MFA与Session.md`
- `docs/spec/10-安全设计.md`
- `docs/verification/004-session.md`
- `docs/verification/005-mfa.md`

实现：

- session management
- online status
- revoke one
- revoke all
- SUPER_ADMIN protection
- MFA provider abstraction
- user/role MFA policy

注意：

V1 MFA Provider 未冻结。

不得自行把某个具体 Provider 宣布为最终业务需求。
