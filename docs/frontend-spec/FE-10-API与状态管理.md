# FE-10 API 与状态管理

## 1. API Client
统一处理 Base URL、Authorization、X-Trace-ID、X-Request-ID、Response Envelope、Error、401、403、Refresh。

## 2. Trace
每个请求支持 X-Trace-ID、X-Request-ID，并遵循后端 Contract。

## 3. Response

成功：
```json
{"code":0,"message":"success","data":{}}
```

失败：
```json
{"code":403001,"message":"permission denied","data":null}
```

## 4. ID
```ts
type ID = string
```
禁止 Number(id) 等方式承载 BIGINT 业务 ID。

## 5. Store
Store 管理跨页面共享状态；临时页面状态留在组件内部，不把所有 API 数据无差别塞入 Pinia。
