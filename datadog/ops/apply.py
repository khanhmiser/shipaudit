"""[A] Tạo hoặc cập nhật dashboard và monitor vận hành trên Datadog từ JSON trong thư mục này.

    python datadog/ops/apply.py --dry-run                      # chỉ in ra, không gọi Datadog
    python datadog/ops/apply.py                                # tạo / cập nhật (cần DD_API_KEY, DD_APP_KEY)
    python datadog/ops/apply.py --notify @webhook-shipaudit-claims    # gắn thêm handle thông báo vào message monitor

- Nguồn: `dashboard.json`, `monitors.json`. Sửa ở đây rồi chạy lại; tìm theo đúng tên nên chạy lại không tạo bản trùng.
- Trong message monitor: `$UI_URL` thay bằng --ui-url, `$NOTIFY` thay bằng --notify (mặc định bỏ trống).
- Site lấy từ DD_SITE (của đội: uk1.datadoghq.com). Khóa chỉ đọc từ .env, không in ra.
- Ghi id và đường dẫn vào `deployed.json` (không có bí mật).
- Không đụng tới dashboard / monitor khác của tổ chức.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_UI_URL = "http://localhost:8501"


def load_definitions() -> tuple[dict, list[dict]]:
    dashboard = json.loads((HERE / "dashboard.json").read_text(encoding="utf-8"))
    monitors = json.loads((HERE / "monitors.json").read_text(encoding="utf-8"))
    return dashboard, monitors


def render_monitor(monitor: dict, ui_url: str, notify: str) -> dict:
    out = json.loads(json.dumps(monitor))
    msg = out["message"].replace("$UI_URL", ui_url.rstrip("/")).replace("$NOTIFY", notify)
    out["message"] = msg.rstrip()
    return out


def app_host(site: str) -> str:
    return "app.datadoghq.com" if site == "datadoghq.com" else site


class DatadogApi:
    def __init__(self, api_key: str, app_key: str, site: str, opener: Callable = urllib.request.urlopen):
        self.base = f"https://api.{site}"
        self._headers = {"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key,
                         "Content-Type": "application/json", "Accept": "application/json"}
        self._opener = opener

    def call(self, method: str, path: str, body: dict | None = None, params: dict | None = None):
        url = self.base + path + (f"?{urllib.parse.urlencode(params)}" if params else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers)
        try:
            with self._opener(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read()[:800].decode(errors="replace")
            raise RuntimeError(f"{method} {path} -> {e.code}: {detail}") from None
        return json.loads(raw) if raw else None

    # ── Dashboard ──
    def upsert_dashboard(self, dashboard: dict) -> tuple[str, str]:
        found = self.call("GET", "/api/v1/dashboard", params={"filter[shared]": "false"}) or {}
        same = [d for d in found.get("dashboards", []) if d.get("title") == dashboard["title"]]
        if same:
            res = self.call("PUT", f"/api/v1/dashboard/{same[0]['id']}", dashboard)
            return "cập nhật", res["id"]
        res = self.call("POST", "/api/v1/dashboard", dashboard)
        return "tạo mới", res["id"]

    # ── Monitor ──
    def upsert_monitor(self, monitor: dict) -> tuple[str, int]:
        self.call("POST", "/api/v1/monitor/validate", monitor)
        found = self.call("GET", "/api/v1/monitor", params={"name": monitor["name"]}) or []
        same = [m for m in found if m.get("name") == monitor["name"]]
        if same:
            res = self.call("PUT", f"/api/v1/monitor/{same[0]['id']}", monitor)
            return "cập nhật", res["id"]
        res = self.call("POST", "/api/v1/monitor", monitor)
        return "tạo mới", res["id"]


def apply(api: DatadogApi, dashboard: dict | None, monitors: list[dict], site: str) -> dict:
    host = app_host(site)
    deployed: dict = {"site": site, "monitors": []}
    for m in monitors:
        action, mid = api.upsert_monitor(m)
        url = f"https://{host}/monitors/{mid}"
        deployed["monitors"].append({"name": m["name"], "id": mid, "url": url})
        print(f"monitor {action}: {m['name']} -> {url}")
    if dashboard is not None:
        action, did = api.upsert_dashboard(dashboard)
        url = f"https://{host}/dashboard/{did}"
        deployed["dashboard"] = {"title": dashboard["title"], "id": did, "url": url}
        print(f"dashboard {action}: {dashboard['title']} -> {url}")
    return deployed


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Tạo / cập nhật dashboard và monitor vận hành ShipAudit")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", choices=["all", "dashboard", "monitors"], default="all")
    parser.add_argument("--ui-url", default=os.getenv("SHIPAUDIT_UI_URL", DEFAULT_UI_URL))
    parser.add_argument("--notify", default="", help="handle thông báo, vd @webhook-shipaudit-claims")
    args = parser.parse_args(argv)

    dashboard, monitors = load_definitions()
    monitors = [render_monitor(m, args.ui_url, args.notify) for m in monitors]
    if args.only == "dashboard":
        monitors = []
    if args.only == "monitors":
        dashboard = None

    if args.dry_run:
        for m in monitors:
            print(f"[dry-run] monitor: {m['name']}\n          {m['query']}")
        if dashboard is not None:
            print(f"[dry-run] dashboard: {dashboard['title']} ({len(dashboard['widgets'])} widget gốc)")
        return 0

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    api_key, app_key = os.getenv("DD_API_KEY", ""), os.getenv("DD_APP_KEY", "")
    if not api_key or not app_key:
        print("Thiếu DD_API_KEY hoặc DD_APP_KEY trong .env (tạo Application Key ở Organization Settings).",
              file=sys.stderr)
        return 2
    site = os.getenv("DD_SITE", "datadoghq.com")
    try:
        deployed = apply(DatadogApi(api_key, app_key, site), dashboard, monitors, site)
    except RuntimeError as e:
        print(f"Lỗi Datadog API: {e}", file=sys.stderr)
        return 1
    path = HERE / "deployed.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if args.only == "dashboard":
        deployed["monitors"] = previous.get("monitors", [])
    if args.only == "monitors" and "dashboard" in previous:
        deployed["dashboard"] = previous["dashboard"]
    path.write_text(json.dumps(deployed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
