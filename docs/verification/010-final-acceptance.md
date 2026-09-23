# Verification 010 — Final Acceptance

## Build

- [ ] Backend can start
- [ ] Database migration succeeds
- [ ] Redis connection succeeds
- [ ] Health check succeeds

## Functional

- [ ] Organization
- [ ] User
- [ ] Role
- [ ] Permission
- [ ] Authentication
- [ ] Session
- [ ] MFA
- [ ] Logs
- [ ] Audit
- [ ] Trace
- [ ] Dictionary
- [ ] Dynamic Permission

## Security

- [ ] API authorization
- [ ] Data scope
- [ ] SUPER_ADMIN protection
- [ ] Password policy
- [ ] Account lockout
- [ ] Session revocation
- [ ] MFA
- [ ] Sensitive masking

## Permission Matrix

至少验证：

- [ ] SUPER_ADMIN
- [ ] Department Admin
- [ ] Normal User
- [ ] 多角色用户
- [ ] 有继承角色用户

## Final Rule

所有 P0 / 高危安全问题必须为 PASS。

最终状态只能是：

PASS / FAIL / BLOCKED
