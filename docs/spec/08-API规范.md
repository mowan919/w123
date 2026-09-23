# 08 API 规范

## 1. Base

```text
/api/v1/admin
```

## 2. Response

成功：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

失败：

```json
{
  "code": 403001,
  "message": "permission denied",
  "data": null
}
```

ID 统一 JSON string。

## 3. Auth

- POST `/auth/login`
- POST `/auth/mfa/verify`
- POST `/auth/refresh`
- POST `/auth/logout`
- GET `/auth/me`
- GET `/auth/permissions`
- GET `/auth/mfa`
- POST `/auth/mfa/setup`
- POST `/auth/mfa/enable`
- POST `/auth/mfa/disable`

## 4. Users

- GET/POST `/users`
- GET/PUT `/users/{id}`
- POST `/users/{id}/disable`
- POST `/users/{id}/enable`
- POST `/users/{id}/reset-password`
- GET `/users/{id}/sessions`
- POST `/users/{id}/sessions/revoke-all`

## 5. Sessions

- GET `/sessions`
- POST `/sessions/{id}/revoke`

## 6. Departments

- GET `/departments/tree`
- POST `/departments`
- PUT `/departments/{id}`
- POST `/departments/{id}/disable`

## 7. Roles

- GET/POST `/roles`
- PUT `/roles/{id}`
- POST `/roles/{id}/delete`
- GET `/roles/{id}/permissions`
- PUT `/roles/{id}/permissions/pages`
- PUT `/roles/{id}/permissions/menus`
- PUT `/roles/{id}/permissions/buttons`
- PUT `/roles/{id}/permissions/apis`
- PUT `/roles/{id}/permissions/fields`
- GET/PUT `/roles/{id}/data-scope`

## 8. Audit / Trace

- GET `/audit/logs`
- GET `/audit/logs/{id}`
- GET `/traces`
- GET `/traces/{traceId}`

## 9. Dictionary

- GET/POST `/api/v1/admin/dicts`
- GET/PUT/DELETE `/api/v1/admin/dicts/{id}`
- GET/POST `/api/v1/admin/dicts/{id}/items`
- PUT/DELETE `/api/v1/admin/dicts/{id}/items/{itemId}`
- GET `/api/v1/dicts/{dictCode}`

## 10. API Authorization

每个受保护 API 必须经过后端 API Permission 校验。

同时应用 Data Scope。

禁止仅依赖 URL 隐藏、菜单隐藏或按钮隐藏。
