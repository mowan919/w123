# Verification 006 — Logging / Audit / Trace

## 日志类型

- [ ] Access Log
- [ ] Security Log
- [ ] Operation Log
- [ ] Audit Log
- [ ] Application Log

## Trace

- [ ] X-Trace-ID
- [ ] X-Request-ID
- [ ] 无 Header 时自动生成
- [ ] HTTP → Controller → Service → Repository → Log 链路一致

## Audit

- [ ] audit_log_id
- [ ] trace_id
- [ ] request_id
- [ ] operator_id
- [ ] operator_username
- [ ] action
- [ ] resource_type
- [ ] resource_id
- [ ] before_data
- [ ] after_data
- [ ] result
- [ ] error_code
- [ ] ip
- [ ] user_agent
- [ ] created_at
- [ ] Audit append-only

## Masking

- [ ] phone → 138****1234
- [ ] email → abc***@example.com
- [ ] token → only first 6 chars
- [ ] password → never log
- [ ] MFA Secret → never log

## Retention

- [ ] Access Log 30 days
- [ ] Security Log 180 days
- [ ] Operation Log 180 days
- [ ] Audit Log 2 years
- [ ] Application Log 30 days
