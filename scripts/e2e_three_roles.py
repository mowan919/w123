"""E2E 三角色契约校验（FE-12 §4）。

为什么需要"三份不同数据"才能真正验证
----------------------------------
早先的 E2E 只跑一个 SUPER_ADMIN：能登录、能取到契约，就算过了。
但"有权限"和"没权限"都返回空集合时，测试同样是通过的 ——
判据必须是**同一套请求在三个角色下的不同结果**，否则等于没测。

本脚本对 SUPER_ADMIN / DEPARTMENT_ADMIN / VIEWER 三个账号做三件事：
1. 登录并取 `/auth/permissions`，核对契约七段；
2. 核对**字段权限的四级差异**（同一字段三个角色取值必须不同）；
3. 核对**越权方向**：无 API 权限的写操作必须 403，且前端隐藏按钮
   不能替代后端兜底（直接打接口照样被拒）。
另外核对安全底线：`password` / `token` 绝不出现在响应体里。

用法
----
    .venv\\Scripts\\python.exe scripts\\e2e_three_roles.py [--base-url http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

#: 与 `scripts/seed_e2e.py` 一一对应。
ACCOUNTS: list[dict[str, Any]] = [
    {
        "username": "admin",
        "password": "E2e@Super2026",
        "label": "SUPER_ADMIN",
        "expect_pages": 10,
        "data_scope": "ALL",
        "expect_phone_field": "READ_ONLY",
    },
    {
        "username": "deptadmin",
        "password": "E2e@Dept2026",
        "label": "DEPARTMENT_ADMIN",
        "expect_pages": 4,
        "data_scope": "DEPARTMENT_CHILDREN",
        "expect_phone_field": "VISIBLE",
    },
    {
        "username": "viewer",
        "password": "E2e@Viewer2026",
        "label": "VIEWER",
        "expect_pages": 2,
        "data_scope": "SELF",
        "expect_phone_field": "HIDDEN",
    },
]

#: 敏感字段名：作为**键**出现在任意层级即判定失败。
#:
#: 只查键、不查子串 —— 登录响应里必然有 `must_change_password` 这个布尔字段，
#: 用 `password` 做子串匹配会把每次正常登录都判成失败（实测踩过）。
SENSITIVE_KEYS = (
    "password",
    "password_hash",
    "password_hash_algorithm",
    "mfa_secret",
    "mfa_secret_encrypted",
    "secret",
)

#: 信封顶层键。`08 §2` 冻结为 `{code, message, data}`。
ENVELOPE_KEYS = ("code", "message", "data")


def opener() -> urllib.request.OpenerDirector:
    """禁用本机代理 —— 否则 127.0.0.1 上的请求会被代理拦成 502。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(  # noqa: S310
        f"{base_url}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with opener().open(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        try:
            return error.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return error.code, raw


def data_of(payload: Any) -> Any:
    if isinstance(payload, dict) and "code" in payload and "data" in payload:
        return payload["data"]
    return payload


def sensitive_keys_of(payload: Any) -> list[str]:
    """递归收集响应体里出现的敏感字段名（按出现顺序去重）。"""
    found: list[str] = []
    stack: list[Any] = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key in SENSITIVE_KEYS and key not in found:
                    found.append(key)
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return found


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, ok: bool, message: str) -> bool:
        if ok:
            print(f"  ✓ {message}")
        else:
            print(f"  ✗ {message}")
            self.failures.append(message)
        return ok

    def section(self, title: str) -> None:
        print(f"\n{title}")


def main() -> int:
    parser = argparse.ArgumentParser(description="E2E 三角色契约校验")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    report = Report()
    sessions: list[dict[str, Any]] = []

    for account in ACCOUNTS:
        label = account["label"]
        print(f"\n=== {label} ({account['username']}) ===")

        raw_code, payload = call(
            base,
            "POST",
            "/api/v1/auth/login",
            body={"username": account["username"], "password": account["password"]},
        )
        if not report.check(raw_code == 200, f"登录返回 200（实际 {raw_code}）"):
            continue
        token_data = data_of(payload) or {}
        access = token_data.get("access_token")
        refresh = token_data.get("refresh_token")
        report.check(access is not None, "登录响应带 access_token")

        # 令牌**本来就该**出现在登录响应里（那是登录的目的），所以"不含令牌"
        # 是个假命题。真正该守的是两条：敏感字段一个键都不许有，
        # 以及令牌只能待在 `data` 段里 —— 被抄进 `message` 或信封顶层就是事故。
        report.check(
            not sensitive_keys_of(payload),
            f"登录响应不含敏感字段（命中 {sensitive_keys_of(payload)}）",
        )
        envelope_without_data = json.dumps(
            {k: v for k, v in payload.items() if k != "data"}, ensure_ascii=False
        )
        leaked = [
            name
            for name, value in (("access_token", access), ("refresh_token", refresh))
            if isinstance(value, str) and len(value) > 8 and value in envelope_without_data
        ]
        report.check(not leaked, f"令牌只出现在 data 段（泄漏到信封 {leaked}）")
        report.check(
            tuple(payload.keys()) == ENVELOPE_KEYS,
            f"信封顶层键 == {ENVELOPE_KEYS}（实际 {tuple(payload.keys())}）",
        )

        status, contract = call(base, "GET", "/api/v1/auth/permissions", token=access)
        if not report.check(status == 200, f"/auth/permissions 返回 200（实际 {status}）"):
            continue
        contract = data_of(contract) or {}

        pages = contract.get("pages") or []
        report.check(
            len(pages) == account["expect_pages"],
            f"页面数 {len(pages)} == {account['expect_pages']}",
        )
        report.check(
            contract.get("is_super_admin") is (label == "SUPER_ADMIN"),
            f"is_super_admin == {label == 'SUPER_ADMIN'}",
        )
        scope = (contract.get("data_scope") or {}).get("policy")
        report.check(
            scope == account["data_scope"], f"data_scope.policy == {account['data_scope']}"
        )
        report.check(
            isinstance(contract.get("permission_version"), int),
            "permission_version 是整数",
        )

        page_codes = {item["code"] for item in pages}
        report.check(
            "system:user:page" in page_codes,
            "持有 system:user:page",
        )

        # 菜单必须跟着页一起给。曾经 `seed_e2e.py` 里查菜单授权用的是裸字符串，
        # 而 `resource_id` 的键全是二元组 —— 那个判断恒为 False，
        # 于是"页面都给全了、菜单一个没给"。这里补一条断言把它钉死：
        # 菜单为空时前端侧边栏会是空的，而页面数、字段权限全都照样对得上。
        menus = contract.get("menus") or []
        report.check(len(menus) > 0, f"菜单非空（{len(menus)} 项）")
        if label == "SUPER_ADMIN":
            report.check(
                "system:param:page" in page_codes,
                "持有 system:param:page（超管视角应看得见全部页面）",
            )
        else:
            report.check(
                "system:param:page" not in page_codes,
                "不持有 system:param:page",
            )

        fields = {item["field_key"]: item["access_level"] for item in contract.get("fields") or []}
        report.check(
            fields.get("phone") == account["expect_phone_field"],
            f"字段 phone == {account['expect_phone_field']}（实际 {fields.get('phone')}）",
        )

        # ---- 令牌不出现在任意响应里 ----
        code, body = call(base, "GET", "/api/v1/auth/me", token=access)
        me_text = json.dumps(body, ensure_ascii=False) if body is not None else ""
        report.check(
            isinstance(body, dict) and (data_of(body) or {}).get("username") == account["username"],
            f"/auth/me 指回本人（实际 code={code}）",
        )
        report.check(
            isinstance(access, str) and access not in me_text,
            "access_token 不出现在 /auth/me 响应里",
        )

        # ---- 同一请求在三个角色下的结果，存进 sessions 供跨角色比对 ----
        code, list_payload = call(base, "GET", "/api/v1/admin/users", token=access)
        sessions.append(
            {
                "label": label,
                "access": access,
                "contract": contract,
                "users_code": code,
                "users_total": (data_of(list_payload) or {}).get("total") if code == 200 else None,
            }
        )

    # ---- 越权方向：无权限的写操作必须被后端拒绝 ----
    #
    # 放在循环外，因为它需要三个角色的令牌同时在手（写操作只被 VIEWER 做没意义：
    # 单个角色被拒也可能只是它被禁用了）。真正的结论在「跨角色一致性」里。
    viewer = next((s for s in sessions if s["label"] == "VIEWER"), None)
    if viewer is not None:
        code, _ = call(base, "POST", "/api/v1/admin/users", token=viewer["access"], body={})
        report.check(code == 403, f"VIEWER 无 USER_MANAGE → 写操作被拒 403（实际 {code}）")

        code, _ = call(base, "POST", "/api/v1/admin/departments", token=viewer["access"], body={})
        report.check(code == 403, f"VIEWER 无 DEPARTMENT_MANAGE → 部门写操作 403（实际 {code}）")

    # ---- 跨角色：同一请求必须给出不同结果 ----
    print("\n=== 跨角色一致性 ===")
    by_label = {s["label"]: s for s in sessions}
    if {"SUPER_ADMIN", "DEPARTMENT_ADMIN", "VIEWER"} <= set(by_label):
        codes = {label: by_label[label]["users_code"] for label in by_label}
        report.check(
            codes["SUPER_ADMIN"] == 200 and codes["DEPARTMENT_ADMIN"] == 200,
            f"GET /admin/users：超管 {codes['SUPER_ADMIN']} "
            f"/ 部门管理员 {codes['DEPARTMENT_ADMIN']}",
        )
        report.check(
            codes["VIEWER"] == 403,
            f"GET /admin/users：只读用户被拒 {codes['VIEWER']}（前端隐藏按钮不能替代后端兜底）",
        )
        super_total = by_label["SUPER_ADMIN"]["users_total"]
        dept_total = by_label["DEPARTMENT_ADMIN"]["users_total"]
        report.check(
            isinstance(super_total, int)
            and isinstance(dept_total, int)
            and dept_total < super_total,
            f"数据范围下推：超管看到 {super_total} 人 > 部门管理员看到 {dept_total} 人",
        )

    print()
    if report.failures:
        print(f"E2E 失败：{len(report.failures)} 项")
        for failure in report.failures:
            print(f"  - {failure}")
        return 1
    print("E2E 三角色校验全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
