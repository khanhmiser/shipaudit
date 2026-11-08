"""[B] Tạo hoặc cập nhật các đối tượng Datadog nghiệp vụ từ JSON trong thư mục này.

    python datadog/biz/apply.py --dry-run                      # chỉ in ra, không gọi Datadog
    python datadog/biz/apply.py                                # tạo / cập nhật tất cả (cần DD_API_KEY, DD_APP_KEY)
    python datadog/biz/apply.py --notify @webhook-shipaudit-claims --case-handle @case-shipaudit
    python datadog/biz/apply.py --only monitors                # một phần: logs | slos | notebook | monitors | dashboard

- Nguồn: `logs.json` (pipeline log + log-based metric), `slos.json`, `notebook.json`, `monitors.json`, `dashboard.json`.
  Tìm theo đúng tên (log-based metric theo id) nên chạy lại không tạo bản trùng.
- Thứ tự: log → SLO → notebook → monitor (monitor gộp sau cùng) → dashboard, vì đối tượng sau tham chiếu đối tượng trước:
  `$REF[khóa]` thay bằng id của đối tượng có `x_ref` = khóa, hoặc `$REF[notebook_url]`. Không tạo ở lần chạy này thì lấy
  từ `deployed.json` của lần trước.
- Thay trong nội dung: `$UI_URL` (--ui-url), `$DD_APP` (https://<site>), và trong message monitor: `$NOTIFY` (--notify),
  `$CASE` (--case-handle: handle Case Management dạng @case-<handle>, lấy ở Project Settings > Integrations > Datadog Monitors).
- Site lấy từ DD_SITE (của đội: uk1.datadoghq.com). Khóa chỉ đọc từ .env, không in ra.
- Ghi id và đường dẫn vào `deployed.json` (không có bí mật). Không đụng tới đối tượng khác của tổ chức.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_UI_URL = "http://localhost:8501"
PARTS = ("logs", "slos", "notebook", "monitors", "dashboard")
_REF = re.compile(r"\$REF\[(\w+)\]")


def _read(name: str):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def load_definitions() -> tuple[dict, list[dict]]:
    return _read("dashboard.json"), _read("monitors.json")


def load_all() -> dict:
    dashboard, monitors = load_definitions()
    return {"dashboard": dashboard, "monitors": monitors, "slos": _read("slos.json"),
            "notebook": _read("notebook.json"), "logs": _read("logs.json")}


def app_host(site: str) -> str:
    return "app.datadoghq.com" if site == "datadoghq.com" else site


def _map_strings(obj, fn: Callable[[str], str]):
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [_map_strings(v, fn) for v in obj]
    if isinstance(obj, dict):
        return {k: _map_strings(v, fn) for k, v in obj.items()}
    return obj


def fill_static(obj, ui_url: str, app_url: str):
    """Thay $UI_URL và $DD_APP ở mọi chuỗi (bản gốc không bị sửa)."""
    return _map_strings(obj, lambda s: s.replace("$UI_URL", ui_url.rstrip("/")).replace("$DD_APP", app_url.rstrip("/")))


def resolve_refs(obj, refs: dict):
    """Thay $REF[khóa] bằng id hoặc URL đã biết. Thiếu khóa thì báo lỗi rõ ràng."""
    def sub(s: str) -> str:
        def one(m: re.Match) -> str:
            if m.group(1) not in refs:
                raise RuntimeError(f"chưa có $REF[{m.group(1)}]: tạo đối tượng đó trước (chạy không có --only)")
            return str(refs[m.group(1)])
        return _REF.sub(one, s)
    return _map_strings(obj, sub)


def strip_ref(obj: dict) -> tuple[str | None, dict]:
    body = {k: v for k, v in obj.items() if k != "x_ref"}
    return obj.get("x_ref"), body


def render_monitor(monitor: dict, ui_url: str, notify: str, case: str = "", app_url: str = "") -> dict:
    out = fill_static(json.loads(json.dumps(monitor)), ui_url, app_url)
    out["message"] = out["message"].replace("$NOTIFY", notify).replace("$CASE", case).rstrip()
    return out


def refs_from(deployed: dict) -> dict:
    """Id / URL của lần chạy trước, để chạy một phần (--only) vẫn điền được $REF."""
    refs = {e["ref"]: e["id"] for e in deployed.get("monitors", []) + deployed.get("slos", []) if e.get("ref")}
    if deployed.get("notebook"):
        refs["notebook_url"] = deployed["notebook"]["url"]
    return refs


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

    # ── SLO ──
    def upsert_slo(self, slo: dict) -> tuple[str, str]:
        found = (self.call("GET", "/api/v1/slo", params={"query": slo["name"]}) or {}).get("data") or []
        same = [s for s in found if s.get("name") == slo["name"]]
        if same:
            res = self.call("PUT", f"/api/v1/slo/{same[0]['id']}", slo)
            return "cập nhật", res["data"][0]["id"]
        res = self.call("POST", "/api/v1/slo", slo)
        return "tạo mới", res["data"][0]["id"]

    # ── Notebook ──
    def upsert_notebook(self, notebook: dict) -> tuple[str, int]:
        attrs = {k: v for k, v in notebook.items() if k != "cells"}
        attrs["cells"] = [{"type": "notebook_cells", "attributes": c} for c in notebook["cells"]]
        body = {"data": {"type": "notebooks", "attributes": attrs}}
        found = (self.call("GET", "/api/v1/notebooks", params={"query": notebook["name"]}) or {}).get("data") or []
        same = [n for n in found if (n.get("attributes") or {}).get("name") == notebook["name"]]
        if same:
            res = self.call("PUT", f"/api/v1/notebooks/{same[0]['id']}", body)
            return "cập nhật", res["data"]["id"]
        res = self.call("POST", "/api/v1/notebooks", body)
        return "tạo mới", res["data"]["id"]

    # ── Log: pipeline và log-based metric ──
    def upsert_logs_pipeline(self, pipeline: dict) -> tuple[str, str]:
        found = self.call("GET", "/api/v1/logs/config/pipelines") or []
        same = [p for p in found if p.get("name") == pipeline["name"]]
        if same:
            res = self.call("PUT", f"/api/v1/logs/config/pipelines/{same[0]['id']}", pipeline)
            return "cập nhật", res["id"]
        res = self.call("POST", "/api/v1/logs/config/pipelines", pipeline)
        return "tạo mới", res["id"]

    def upsert_logs_metric(self, metric: dict) -> tuple[str, str]:
        mid = metric["id"]
        try:
            self.call("GET", f"/api/v2/logs/config/metrics/{mid}")
        except RuntimeError as e:
            if "-> 404" not in str(e):
                raise
            attrs = {k: metric[k] for k in ("compute", "filter", "group_by") if k in metric}
            self.call("POST", "/api/v2/logs/config/metrics", {"data": {"id": mid, "type": "logs_metrics", "attributes": attrs}})
            return "tạo mới", mid
        attrs = {k: metric[k] for k in ("filter", "group_by") if k in metric}  # compute không đổi được sau khi tạo
        self.call("PATCH", f"/api/v2/logs/config/metrics/{mid}", {"data": {"type": "logs_metrics", "attributes": attrs}})
        return "cập nhật", mid


def apply(api: DatadogApi, dashboard: dict | None, monitors: list[dict], site: str, slos: list[dict] = (),
          notebook: dict | None = None, logs: dict | None = None, refs: dict | None = None) -> dict:
    host = app_host(site)
    refs = dict(refs or {})
    deployed: dict = {"site": site}
    if logs:
        action, pid = api.upsert_logs_pipeline(logs["pipeline"])
        print(f"log pipeline {action}: {logs['pipeline']['name']}")
        deployed["logs"] = {"pipeline": {"name": logs["pipeline"]["name"], "id": pid}, "metrics": []}
        for m in logs.get("metrics", []):
            action, mid = api.upsert_logs_metric(m)
            print(f"log-based metric {action}: {mid}")
            deployed["logs"]["metrics"].append(mid)
    if slos:
        deployed["slos"] = []
        for s in slos:
            key, body = strip_ref(s)
            action, sid = api.upsert_slo(resolve_refs(body, refs))
            url = f"https://{host}/slo?slo_id={sid}"
            if key:
                refs[key] = sid
            deployed["slos"].append({"name": body["name"], "ref": key, "id": sid, "url": url})
            print(f"SLO {action}: {body['name']} -> {url}")
    if notebook:
        action, nid = api.upsert_notebook(resolve_refs(notebook, refs))
        url = f"https://{host}/notebook/{nid}"
        refs["notebook_url"] = url
        deployed["notebook"] = {"name": notebook["name"], "id": nid, "url": url}
        print(f"notebook {action}: {notebook['name']} -> {url}")
    if monitors:
        deployed["monitors"] = []
        # monitor gộp tham chiếu id của monitor khác nên tạo sau cùng
        for m in sorted(monitors, key=lambda m: m.get("type") == "composite"):
            key, body = strip_ref(m)
            action, mid = api.upsert_monitor(resolve_refs(body, refs))
            url = f"https://{host}/monitors/{mid}"
            if key:
                refs[key] = mid
            deployed["monitors"].append({"name": body["name"], "ref": key, "id": mid, "url": url})
            print(f"monitor {action}: {body['name']} -> {url}")
    if dashboard is not None:
        action, did = api.upsert_dashboard(resolve_refs(dashboard, refs))
        url = f"https://{host}/dashboard/{did}"
        deployed["dashboard"] = {"title": dashboard["title"], "id": did, "url": url}
        print(f"dashboard {action}: {dashboard['title']} -> {url}")
    return deployed


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:  # nạp .env trước khi đọc giá trị mặc định của tham số (SHIPAUDIT_CASE_HANDLE, SHIPAUDIT_UI_URL)
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description="Tạo / cập nhật các đối tượng Datadog nghiệp vụ ShipAudit")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", choices=["all", *PARTS], default="all")
    parser.add_argument("--ui-url", default=os.getenv("SHIPAUDIT_UI_URL", DEFAULT_UI_URL))
    parser.add_argument("--notify", default="", help="handle thông báo, vd @webhook-shipaudit-claims")
    parser.add_argument("--case-handle", default=os.getenv("SHIPAUDIT_CASE_HANDLE", ""),
                        help="handle Case Management, vd @case-shipaudit (mở case khi monitor gộp báo động)")
    args = parser.parse_args(argv)

    site = os.getenv("DD_SITE", "datadoghq.com")
    app_url = f"https://{app_host(site)}"
    d = load_all()
    parts = {p: (args.only in ("all", p)) for p in PARTS}
    monitors = [render_monitor(m, args.ui_url, args.notify, args.case_handle, app_url) for m in d["monitors"]]
    picked = {
        "logs": d["logs"] if parts["logs"] else None,
        "slos": d["slos"] if parts["slos"] else [],
        "notebook": fill_static(d["notebook"], args.ui_url, app_url) if parts["notebook"] else None,
        "monitors": monitors if parts["monitors"] else [],
        "dashboard": fill_static(d["dashboard"], args.ui_url, app_url) if parts["dashboard"] else None,
    }

    if args.dry_run:
        if picked["logs"]:
            print(f"[dry-run] log pipeline: {picked['logs']['pipeline']['name']}; log-based metric: "
                  + ", ".join(m["id"] for m in picked["logs"]["metrics"]))
        for s in picked["slos"]:
            print(f"[dry-run] SLO: {s['name']}")
        if picked["notebook"]:
            print(f"[dry-run] notebook: {picked['notebook']['name']} ({len(picked['notebook']['cells'])} ô)")
        for m in picked["monitors"]:
            print(f"[dry-run] monitor ({m['type']}): {m['name']}\n          {m['query']}")
        if picked["dashboard"] is not None:
            print(f"[dry-run] dashboard: {picked['dashboard']['title']} ({len(picked['dashboard']['widgets'])} widget gốc)")
        return 0

    api_key, app_key = os.getenv("DD_API_KEY", ""), os.getenv("DD_APP_KEY", "")
    if not api_key or not app_key:
        print("Thiếu DD_API_KEY hoặc DD_APP_KEY trong .env (tạo Application Key ở Organization Settings).",
              file=sys.stderr)
        return 2
    path = HERE / "deployed.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    try:
        deployed = apply(DatadogApi(api_key, app_key, site), picked["dashboard"], picked["monitors"], site,
                         slos=picked["slos"], notebook=picked["notebook"], logs=picked["logs"], refs=refs_from(previous))
    except RuntimeError as e:
        print(f"Lỗi Datadog API: {e}", file=sys.stderr)
        return 1
    merged = {**{k: v for k, v in previous.items() if k != "created_via"}, **deployed}
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
