# 04 认证、MFA 与 Session

## 1. Login

流程：

```text
username/password
 ↓
user lookup
 ↓
status check
 ↓
lock check
 ↓
password verify
 ↓
MFA check
 ↓
create session
 ↓
issue token
 ↓
audit/security log
 ↓
response
```

## 2. Password

- >= 12
- uppercase
- lowercase
- digit
- special
- last 5 passwords cannot repeat
- 90 days
- 5 consecutive failures → 30 minutes lock
- admin reset → first login force change

## 3. Session

必须记录：

- session id
- user id
- login time
- last active
- IP
- user agent
- device
- expires_at
- revoked_at
- revoke_reason
- token identifiers

Refresh Token 必须哈希存储，不得保存明文。

## 4. Kick

支持：

- revoke one session
- revoke all sessions

SUPER_ADMIN：

- 可 revoke 正常用户
- 不能被其他管理员 revoke
- 仅本人 logout

Department Admin：

- 只能 revoke 管理范围内正常用户

## 5. Online Status

在线状态由有效 Session / 最近活动等规则计算。

后台应提供在线用户查询。

## 6. MFA

MFA Provider 必须抽象，例如：

```python
class MfaProvider:
    setup()
    verify()
    enable()
    disable()
```

生命周期：

```text
DISABLED
SETUP
ENABLED
```

Secret 必须加密保存。

## 7. MFA Policy

支持：

- system default
- role policy
- user policy

优先级：

```text
user > role > system
```

V1 具体 Provider 尚未冻结。

## 8. 安全日志

记录：

- login success
- login failure
- lockout
- password reset
- password change
- MFA setup/enable/disable/failure
- session revoke
