"""JSON dashboard / monitor vận hành (A8): tên, metric có thật trong app, bố cục không chồng nhau, mẫu webhook."""
import importlib.util
import json
import re
from pathlib import Path

OPS = Path(__file__).resolve().parents[2] / "datadog" / "ops"
APP = Path(__file__).resolve().parents[2] / "app"


def _apply():
    spec = importlib.util.spec_from_file_location("ops_apply", OPS / "apply.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _emitted_metrics() -> set[str]:
    names = set()
    for f in APP.rglob("*.py"):
        names |= set(re.findall(r'"(shipaudit\.ops\.[a-z0-9_.]+)"', f.read_text(encoding="utf-8")))
    names |= {n + suffix for n in names for suffix in (".p95", ".max")}  # timing → .p95, .max
    return names


def _queries(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "query" and isinstance(v, str):
                yield v
            yield from _queries(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _queries(v)


def test_ops_metrics_used_are_emitted_by_app():
    dashboard, monitors = _apply().load_definitions()
    emitted = _emitted_metrics()
    assert "shipaudit.ops.ingest_runs" in emitted and "shipaudit.ops.api_latency_ms.p95" in emitted
    used = {m for q in list(_queries(dashboard)) + [m["query"] for m in monitors]
            for m in re.findall(r"shipaudit\.ops\.[a-z0-9_.]+", q)}
    assert used and used <= emitted, used - emitted


def test_monitor_definitions():
    _, monitors = _apply().load_definitions()
    assert len(monitors) == 4
    for m in monitors:
        assert m["name"].startswith("ShipAudit [ops]")
        assert {"project:shipaudit", "layer:ops"} <= set(m["tags"])
        th = m["options"]["thresholds"]
        assert th["warning"] < th["critical"]
        assert m["query"].endswith(f"> {th['critical']}")
    assert {m["type"] for m in monitors} == {"query alert", "log alert"}
    assert "status:error" in next(m for m in monitors if m["type"] == "log alert")["query"]


def test_dashboard_layout():
    dashboard, _ = _apply().load_definitions()
    assert dashboard["title"].startswith("ShipAudit [ops]")

    def check(widgets):
        cells = set()
        for w in widgets:
            lay = w["layout"]
            assert lay["x"] + lay["width"] <= 12
            for x in range(lay["x"], lay["x"] + lay["width"]):
                for y in range(lay["y"], lay["y"] + lay["height"]):
                    assert (x, y) not in cells
                    cells.add((x, y))
            if w["definition"]["type"] == "group":
                check(w["definition"]["widgets"])

    check(dashboard["widgets"])


def test_webhook_template_matches_api_model():
    from app.api.models import DatadogAlert

    tpl = json.loads((OPS / "webhook.json").read_text(encoding="utf-8"))
    payload = json.loads(tpl["payload"])
    assert payload["alert_id"] == "$ALERT_CYCLE_KEY"
    assert set(payload) <= set(DatadogAlert.model_fields)
    assert "X-ShipAudit-Secret" in json.loads(tpl["custom_headers"])
    assert "$WEBHOOK_SECRET" in tpl["custom_headers"]              # chỗ giữ, không có secret thật
    assert tpl["url"].endswith("/webhooks/datadog")
