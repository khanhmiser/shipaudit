"""Test job metric nghiệp vụ (B9) chạy offline: dựng điểm metric, gửi qua sink, JSON dashboard / monitor.

Phần pipeline open_diffs trên dữ liệu seed thật nằm ở tests/pipelines/test_metrics_job.py (cần Atlas).
"""
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core import metrics_job, metrics_sink
from core.metrics_job import (
    CLAIM_AMOUNT, CLAIM_HOURS_LEFT, CLAIM_STATUSES, DIFF_AMOUNT, DIFF_COUNT, HOURS_CAP, OWED_TYPES, RECOVERED_AMOUNT,
)
from pipelines import claims_outcome, open_diffs

NOW = datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc)
BIZ = Path(__file__).resolve().parents[2] / "datadog" / "biz"
CARRIERS = [{"carrier": "carrier_a"}, {"carrier": "carrier_b"}, {"carrier": "carrier_c"}]


@pytest.fixture
def fake_sources(monkeypatch):
    result = {
        "buckets": [
            {"carrier": "carrier_b", "diff_type": "FEE_MISMATCH", "deadline": "lt24h", "count": 3, "amount": 15_000},
            {"carrier": "carrier_b", "diff_type": "COD_MISMATCH", "deadline": "expired", "count": 1, "amount": 200_000},
            {"carrier": "carrier_a", "diff_type": "MISSING_IN_STATEMENT", "deadline": "later", "count": 2,
             "amount": 900_000},
        ],
        "nearest": [{"carrier": "carrier_b", "min_hours_left": 5.5, "count": 3},
                    {"carrier": "carrier_a", "min_hours_left": 400.0, "count": 2}],
    }
    monkeypatch.setattr(open_diffs, "run", lambda db, now, carrier=None: result)
    monkeypatch.setattr(claims_outcome, "run", lambda db, carrier=None: [
        {"carrier": "carrier_b", "status": "SUBMITTED", "count": 2, "amount": 300_000, "recovered": 0},
        {"carrier": "carrier_b", "status": "RECOVERED", "count": 3, "amount": 450_000, "recovered": 440_000},
        {"carrier": "carrier_a", "status": "REJECTED", "count": 1, "amount": 50_000, "recovered": 0},
    ])
    monkeypatch.setattr(metrics_job.queries, "carriers", lambda db: CARRIERS)
    return result


def _value(points, name, **tags):
    hits = [p.value for p in points if p.name == name and all(p.tags.get(k) == v for k, v in tags.items())]
    assert len(hits) == 1, (name, tags, hits)
    return hits[0]


def test_collect_fills_every_combination_with_zero(fake_sources):
    points = metrics_job.collect(None, NOW)
    per_carrier = len(OWED_TYPES) * len(open_diffs.DEADLINE_BUCKETS) * 2 + 1 + len(CLAIM_STATUSES) + 1
    assert len(points) == 3 * per_carrier
    assert "LATE_PAYOUT" not in OWED_TYPES and "NONE" not in OWED_TYPES
    assert _value(points, DIFF_AMOUNT, carrier="carrier_b", diff_type="FEE_MISMATCH", deadline="lt24h") == 15_000
    assert _value(points, DIFF_COUNT, carrier="carrier_b", diff_type="FEE_MISMATCH", deadline="lt24h") == 3
    assert _value(points, DIFF_AMOUNT, carrier="carrier_c", diff_type="FEE_MISMATCH", deadline="lt24h") == 0
    assert all(p.name.startswith("shipaudit.biz.") for p in points)


def test_claim_outcome_metrics(fake_sources):
    points = metrics_job.collect(None, NOW)
    assert _value(points, CLAIM_AMOUNT, carrier="carrier_b", claim_status="submitted") == 300_000
    assert _value(points, CLAIM_AMOUNT, carrier="carrier_b", claim_status="recovered") == 450_000
    assert _value(points, CLAIM_AMOUNT, carrier="carrier_a", claim_status="rejected") == 50_000
    assert _value(points, CLAIM_AMOUNT, carrier="carrier_c", claim_status="submitted") == 0      # đủ mọi tổ hợp
    assert _value(points, RECOVERED_AMOUNT, carrier="carrier_b") == 440_000                      # hãng hoàn thiếu 10.000
    assert _value(points, RECOVERED_AMOUNT, carrier="carrier_a") == 0


def test_claim_hours_left_is_capped_and_defaults_to_cap(fake_sources):
    points = metrics_job.collect(None, NOW)
    assert _value(points, CLAIM_HOURS_LEFT, carrier="carrier_b") == 5.5
    assert _value(points, CLAIM_HOURS_LEFT, carrier="carrier_a") == HOURS_CAP   # 400 giờ, chặn trên
    assert _value(points, CLAIM_HOURS_LEFT, carrier="carrier_c") == HOURS_CAP   # không còn khoản nào


def test_summary_splits_open_and_expired(fake_sources):
    s = metrics_job.summary(metrics_job.collect(None, NOW))
    assert s["carrier_b"] == {"open_amount": 15_000, "open_count": 3, "expired_amount": 200_000,
                              "claim_hours_left": 5.5}


def test_emit_calls_metric_then_flush(fake_sources):
    calls, flushed = [], []

    class Sink:
        def __call__(self, name, value, tags=None):
            calls.append((name, value, tags))

        def flush(self):
            flushed.append(True)

    points = metrics_job.collect(None, NOW)
    assert metrics_job.emit(points, Sink()) == len(points) == len(calls)
    assert flushed == [True]
    # Hàm thường (như metric() của A hoặc stub_metric) cũng dùng được, không cần flush.
    plain = []
    metrics_job.emit(points[:2], lambda n, v, t=None: plain.append(n))
    assert len(plain) == 2


def test_run_forever_keeps_going_after_an_error(fake_sources, monkeypatch):
    runs = {"n": 0}

    def flaky(db, metric, now):
        runs["n"] += 1
        if runs["n"] == 1:
            raise RuntimeError("Datadog trả 503")
        return []

    monkeypatch.setattr(metrics_job, "run_once", flaky)
    sleeps = []
    metrics_job.run_forever(None, None, 60, lambda: NOW, sleep=sleeps.append, max_runs=3)
    assert runs["n"] == 3 and len(sleeps) == 2


# ── Sink ──
class _Resp:
    def __init__(self, status=202, body=b'{"errors":[]}'):
        self.status, self._body = status, body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_sink_posts_gauges_to_site_and_clears():
    sent = []

    def opener(req, timeout):
        sent.append(req)
        return _Resp()

    sink = metrics_sink.DatadogHttpMetrics("k" * 32, site="uk1.datadoghq.com", base_tags={"env": "dev"},
                                           opener=opener, clock=lambda: 1_760_000_000.9)
    sink("shipaudit.biz.diff_amount", 15_000, {"carrier": "carrier_b", "deadline": "lt24h"})
    assert sink.flush() == 1
    req = sent[0]
    assert req.full_url == "https://api.uk1.datadoghq.com/api/v2/series"
    assert req.get_header("Dd-api-key") == "k" * 32
    series = json.loads(req.data)["series"][0]
    assert series == {"metric": "shipaudit.biz.diff_amount", "type": 3,
                      "points": [{"timestamp": 1_760_000_000, "value": 15000.0}],
                      "tags": ["carrier:carrier_b", "deadline:lt24h", "env:dev"]}
    assert sink.flush() == 0     # đã xóa sau khi gửi


def test_http_sink_error_does_not_leak_key():
    import urllib.error

    def opener(req, timeout):
        raise urllib.error.URLError("timed out")

    sink = metrics_sink.DatadogHttpMetrics("secret-key-123", opener=opener)
    sink("shipaudit.biz.diff_count", 1)
    with pytest.raises(RuntimeError) as e:
        sink.flush()
    assert "secret-key-123" not in str(e.value)

    sink2 = metrics_sink.DatadogHttpMetrics("secret-key-123", opener=lambda req, timeout: _Resp(403, b"Forbidden"))
    sink2("shipaudit.biz.diff_count", 1)
    with pytest.raises(RuntimeError, match="403"):
        sink2.flush()


def test_make_metrics_falls_back_to_console(monkeypatch, capsys):
    monkeypatch.delenv("DD_API_KEY", raising=False)
    sink = metrics_sink.make_metrics("auto")
    assert isinstance(sink, metrics_sink.ConsoleMetrics)
    sink("shipaudit.biz.diff_count", 2, {"carrier": "carrier_a"})
    assert "shipaudit.biz.diff_count=2" in capsys.readouterr().out
    with pytest.raises(RuntimeError):
        metrics_sink.make_metrics("datadog")
    monkeypatch.setenv("DD_API_KEY", "x")
    monkeypatch.setenv("DD_SITE", "uk1.datadoghq.com")
    assert metrics_sink.make_metrics("auto").url == "https://api.uk1.datadoghq.com/api/v2/series"


# ── JSON dashboard / monitor ──
def _load_apply():
    spec = importlib.util.spec_from_file_location("biz_apply", BIZ / "apply.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _queries(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "query" and isinstance(v, str):
                yield v
            yield from _queries(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _queries(v)


KNOWN_METRICS = {DIFF_AMOUNT, DIFF_COUNT, CLAIM_HOURS_LEFT, CLAIM_AMOUNT, RECOVERED_AMOUNT,
                 "shipaudit.biz.logs.claim_actions", "shipaudit.biz.logs.webhook_calls"}


def _check_query(q):
    for name in re.findall(r"shipaudit\.[a-z_.]+", q):
        assert name in KNOWN_METRICS, (name, q)
    for value in re.findall(r"deadline:(\w+)", q):
        assert value in open_diffs.DEADLINE_BUCKETS, q


def test_monitor_definitions():
    apply = _load_apply()
    _, monitors = apply.load_definitions()
    assert [m["x_ref"] for m in monitors] == ["threshold", "deadline", "anomaly", "forecast", "outlier", "composite"]
    for m in monitors:
        assert m["name"].startswith("ShipAudit [biz]") and "{{carrier.name}}" in m["name"]
        assert {"project:shipaudit", "layer:biz"} <= set(m["tags"])
        assert "$REF[notebook_url]" in m["message"]                 # đi thẳng từ cảnh báo sang notebook điều tra
        if m["type"] == "composite":
            continue
        assert m["type"] == "query alert"
        _check_query(m["query"])
        assert "by {carrier}" in m["query"]
    threshold, expiring, anomaly, forecast, outlier, composite = monitors
    assert "forecast(" in forecast["query"] and forecast["query"].startswith("max(next_")
    assert forecast["query"].endswith(f">= {forecast['options']['thresholds']['critical']}")
    assert "outliers(" in outlier["query"]
    assert composite["query"] == "$REF[threshold] && $REF[deadline]"
    assert "$CASE" in composite["message"] and "$CASE" not in threshold["message"]
    assert all("$NOTIFY" not in m["message"] for m in (forecast, outlier, composite))   # webhook chỉ ở 3 monitor gốc
    assert threshold["query"].endswith(f"> {threshold['options']['thresholds']['critical']}")
    assert expiring["query"].endswith(f"< {expiring['options']['thresholds']['critical']}")
    assert expiring["options"]["thresholds"]["warning"] > expiring["options"]["thresholds"]["critical"]
    assert "anomalies(" in anomaly["query"]


def test_render_monitor_fills_placeholders():
    apply = _load_apply()
    _, monitors = apply.load_definitions()
    out = apply.render_monitor(monitors[1], "http://demo:8501/", "@webhook-shipaudit")
    assert "http://demo:8501/han-khieu-nai" in out["message"]
    assert out["message"].endswith("@webhook-shipaudit")
    plain = apply.render_monitor(monitors[1], "http://demo:8501", "")
    assert "$NOTIFY" not in plain["message"] and "$UI_URL" not in plain["message"]
    assert "$UI_URL" in monitors[1]["message"]          # bản gốc không bị sửa


def test_dashboard_layout_and_queries():
    apply = _load_apply()
    dashboard, _ = apply.load_definitions()
    assert dashboard["title"].startswith("ShipAudit [biz]")
    queries = list(_queries(dashboard))
    assert queries
    for q in queries:
        if "shipaudit." in q:
            _check_query(q)

    def check_grid(widgets):
        cells = set()
        for w in widgets:
            lay = w["layout"]
            assert lay["x"] + lay["width"] <= 12
            for x in range(lay["x"], lay["x"] + lay["width"]):
                for y in range(lay["y"], lay["y"] + lay["height"]):
                    assert (x, y) not in cells, f"widget chồng nhau tại {(x, y)}"
                    cells.add((x, y))
            if w["definition"]["type"] == "group":
                check_grid(w["definition"]["widgets"])

    check_grid(dashboard["widgets"])


def test_apply_updates_by_name_and_creates_missing():
    apply = _load_apply()
    calls = []
    existing_monitors = [{"id": 11, "name": "ShipAudit [biz] A"}, {"id": 12, "name": "ShipAudit [biz] A (copy)"}]

    class FakeApi(apply.DatadogApi):
        def __init__(self):
            pass

        def call(self, method, path, body=None, params=None):
            calls.append((method, path))
            if (method, path) == ("GET", "/api/v1/monitor"):
                return [m for m in existing_monitors if params["name"] in m["name"]]
            if (method, path) == ("GET", "/api/v1/dashboard"):
                return {"dashboards": [{"id": "abc-def-ghi", "title": "Khác"}]}
            if method == "POST" and path == "/api/v1/monitor":
                return {"id": 99}
            if method == "POST" and path == "/api/v1/dashboard":
                return {"id": "new-das-hbd"}
            if method == "PUT":
                return {"id": path.rsplit("/", 1)[1]}
            return {}

    out = apply.apply(FakeApi(), {"title": "ShipAudit [biz] D"},
                      [{"name": "ShipAudit [biz] A"}, {"name": "ShipAudit [biz] B"}], "uk1.datadoghq.com")
    assert ("PUT", "/api/v1/monitor/11") in calls           # đúng tên, không đụng bản "(copy)"
    assert ("POST", "/api/v1/monitor") in calls
    assert ("POST", "/api/v1/dashboard") in calls
    assert not any(m == "DELETE" for m, _ in calls)
    assert out["dashboard"]["url"] == "https://uk1.datadoghq.com/dashboard/new-das-hbd"
    assert [m["id"] for m in out["monitors"]] == ["11", 99]


def test_every_ref_has_a_source_and_queries_are_known():
    apply = _load_apply()
    d = apply.load_all()
    sources = {m["x_ref"] for m in d["monitors"]} | {s["x_ref"] for s in d["slos"]} | {"notebook_url"}
    text = json.dumps(d, ensure_ascii=False)
    assert set(re.findall(r"\$REF\[(\w+)\]", text)) <= sources
    for q in _queries(d["slos"]) :
        _check_query(q)
    for q in _queries(d["notebook"]):
        if not q.startswith("service:"):        # ô log_stream là truy vấn log, không phải metric
            _check_query(q)
    slo = d["slos"][0]["sli_specification"]["time_slice"]
    assert slo["comparator"] == ">=" and slo["threshold"] == 24 and "by {carrier}" in slo["query"]["queries"][0]["query"]
    assert [c["definition"]["type"] for c in d["notebook"]["cells"]].count("log_stream") == 2
    assert {m["id"] for m in d["logs"]["metrics"]} == {"shipaudit.biz.logs.claim_actions", "shipaudit.biz.logs.webhook_calls"}
    remapped = {p["target"] for p in d["logs"]["pipeline"]["processors"] if p["type"] == "attribute-remapper"}
    assert {"carrier", "alert_id", "claim_id"} <= remapped


def test_apply_all_parts_in_dependency_order_and_resolves_refs():
    apply = _load_apply()
    d = apply.load_all()
    calls, bodies = [], {}

    class FakeApi(apply.DatadogApi):
        def __init__(self):
            self.next_id = 100

        def call(self, method, path, body=None, params=None):
            calls.append((method, path))
            bodies[(method, path)] = body
            if method == "GET":
                if path.startswith("/api/v2/logs/config/metrics/"):
                    raise RuntimeError(f"GET {path} -> 404: not found")
                return {} if path in ("/api/v1/dashboard", "/api/v1/slo", "/api/v1/notebooks") else []
            self.next_id += 1
            if path == "/api/v1/slo":
                return {"data": [{"id": "slo-abc"}]}
            if path == "/api/v1/notebooks":
                return {"data": {"id": 777}}
            return {"id": self.next_id}

    monitors = [apply.render_monitor(m, "http://ui", "@webhook-x", "@case-shipaudit", "https://uk1.datadoghq.com")
                for m in d["monitors"]]
    out = apply.apply(FakeApi(), d["dashboard"], monitors, "uk1.datadoghq.com", slos=d["slos"],
                      notebook=d["notebook"], logs=d["logs"])
    posts = [p for m, p in calls if m == "POST" and not p.endswith("/validate")]
    assert posts[0] == "/api/v1/logs/config/pipelines" and posts[-1] == "/api/v1/dashboard"
    assert posts.index("/api/v1/slo") < posts.index("/api/v1/notebooks") < posts.index("/api/v1/monitor")
    ids = {m["ref"]: m["id"] for m in out["monitors"]}
    composite = bodies[("POST", "/api/v1/monitor")]                          # monitor gộp tạo sau cùng
    assert composite["type"] == "composite" and composite["query"] == f"{ids['threshold']} && {ids['deadline']}"
    assert "@case-shipaudit" in composite["message"] and "x_ref" not in composite
    assert out["notebook"]["url"] == "https://uk1.datadoghq.com/notebook/777"
    dash = json.dumps(bodies[("POST", "/api/v1/dashboard")], ensure_ascii=False)
    assert "$REF[" not in dash and "slo-abc" in dash and "notebook/777" in dash
    assert out["slos"][0]["ref"] == "slo_deadline" and len(out["logs"]["metrics"]) == 2
    assert not any(m == "DELETE" for m, _ in calls)


def test_missing_ref_is_a_clear_error():
    apply = _load_apply()
    with pytest.raises(RuntimeError, match=r"\$REF\[deadline\]"):
        apply.resolve_refs({"query": "1 && $REF[deadline]"}, {"threshold": 1})
    previous = {"monitors": [{"ref": "threshold", "id": 5}], "notebook": {"url": "u"}}
    assert apply.refs_from(previous) == {"threshold": 5, "notebook_url": "u"}
