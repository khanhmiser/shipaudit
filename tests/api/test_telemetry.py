"""Test telemetry không cần Agent (A6): gửi metric và log thẳng lên Datadog API, middleware đo request."""
import json
import logging
import urllib.error

import pytest

from app.telemetry import http as http_metrics
from app.telemetry.logging import DatadogLogHandler
from app.telemetry.metrics import COUNT, GAUGE, HttpSender, p95


class _Resp:
    status = 202

    def read(self):
        return b"{}"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_p95_nearest_rank():
    assert p95([5]) == 5
    assert p95(list(range(1, 101))) == 95
    assert p95([10, 20, 30, 1000]) == 1000


def test_http_sender_aggregates_and_clears():
    clock = iter([1000.0, 1010.0, 1020.0])
    s = HttpSender("k" * 32, "uk1.datadoghq.com", {"env": "dev"}, clock=lambda: next(clock))
    s.gauge("shipaudit.ops.ingest_lag_seconds", 1.5, {"carrier": "carrier_b"})
    s.gauge("shipaudit.ops.ingest_lag_seconds", 2.5, {"carrier": "carrier_b"})      # gauge giữ giá trị cuối
    s.increment("shipaudit.ops.ingest_errors", 1, {"carrier": "carrier_b"})
    s.increment("shipaudit.ops.ingest_errors", 2, {"carrier": "carrier_b"})         # count cộng dồn
    for ms in (10, 20, 30, 400):
        s.timing("shipaudit.ops.api_latency_ms", ms, {"route": "/statements"})
    series = {x["metric"]: x for x in s.series()}
    assert series["shipaudit.ops.ingest_lag_seconds"]["type"] == GAUGE
    assert series["shipaudit.ops.ingest_lag_seconds"]["points"] == [{"timestamp": 1010, "value": 2.5}]
    assert series["shipaudit.ops.ingest_lag_seconds"]["tags"] == ["carrier:carrier_b", "env:dev"]
    assert series["shipaudit.ops.ingest_errors"]["type"] == COUNT
    assert series["shipaudit.ops.ingest_errors"]["interval"] == 10
    assert series["shipaudit.ops.ingest_errors"]["points"][0]["value"] == 3
    assert series["shipaudit.ops.api_latency_ms.p95"]["points"][0]["value"] == 400
    assert series["shipaudit.ops.api_latency_ms.max"]["points"][0]["value"] == 400
    assert s.series() == []


def test_http_sender_flush_posts_to_site_and_hides_key(caplog):
    sent = []
    s = HttpSender("secret-key-xyz", "uk1.datadoghq.com", opener=lambda req, timeout: sent.append(req) or _Resp())
    s.gauge("shipaudit.ops.fault_delay_ms", 2000)
    assert s.flush() == 1
    assert sent[0].full_url == "https://api.uk1.datadoghq.com/api/v2/series"
    assert json.loads(sent[0].data)["series"][0]["metric"] == "shipaudit.ops.fault_delay_ms"

    def boom(req, timeout):
        raise urllib.error.URLError("down")

    s2 = HttpSender("secret-key-xyz", "uk1.datadoghq.com", opener=boom)
    s2.gauge("x", 1)
    with caplog.at_level(logging.WARNING):
        assert s2.flush() == 0
    assert "secret-key-xyz" not in caplog.text


def test_log_handler_batches_json_to_logs_intake():
    sent = []
    h = DatadogLogHandler("k", "uk1.datadoghq.com", opener=lambda req, timeout: sent.append(req) or _Resp(),
                          start_thread=False)
    logger = logging.getLogger("shipaudit.test.logs")
    logger.addHandler(h)
    logger.propagate = False
    try:
        logger.warning("nạp lỗi", extra={"carrier": "carrier_b", "statement_id": "STM-B-1"})
        h.flush()
    finally:
        logger.removeHandler(h)
    assert sent[0].full_url == "https://http-intake.logs.uk1.datadoghq.com/api/v2/logs"
    item = json.loads(sent[0].data)[0]
    assert item["message"] == "nạp lỗi" and item["carrier"] == "carrier_b" and item["status"] == "warning"
    assert item["ddsource"] == "python" and item["ddtags"].startswith("env:")
    h.flush()
    assert len(sent) == 1     # không còn gì thì không gửi


def test_middleware_times_each_request(client, monkeypatch):
    timings, counts = [], []
    monkeypatch.setattr(http_metrics, "timing", lambda n, v, t=None: timings.append((n, v, t)))
    monkeypatch.setattr(http_metrics, "increment", lambda n, v=1, t=None: counts.append((n, v, t)))
    client.get("/health")
    client.get("/reconciliations", params={"limit": 0})
    assert [t[2]["route"] for t in timings] == ["/health", "/reconciliations"]
    assert all(n == "shipaudit.ops.api_latency_ms" and v >= 0 for n, v, _ in timings)
    assert counts[0][0] == "shipaudit.ops.api_requests"
    assert {c[2]["status_class"] for c in counts} <= {"2xx", "4xx", "5xx"}


@pytest.mark.parametrize("env,expected", [({}, None), ({"DD_API_KEY": "x"}, "http"),
                                          ({"DD_API_KEY": "x", "DD_METRICS_AGENTLESS": "false"}, None)])
def test_client_mode_selection(monkeypatch, env, expected):
    from app.telemetry import metrics

    for k in ("DD_AGENT_HOST", "DD_API_KEY", "DD_METRICS_AGENTLESS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(metrics, "_start_flusher", lambda sender, every: None)
    metrics._client.cache_clear()
    try:
        assert metrics._client()[0] == expected
    finally:
        metrics._client.cache_clear()
