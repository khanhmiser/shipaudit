"""Smoke test (A10): chạy API thật (uvicorn trên cổng tạm) rồi gọi qua HTTP như người dùng, từ trạng thái sạch.

Hai biến thể: MongoDB giả (mongomock, luôn chạy) và MongoDB Atlas (database `<MONGO_DB>_smoke`, bỏ qua khi
không kết nối được hoặc SHIPAUDIT_SKIP_ATLAS=1). Kịch bản lớp vận hành chạy ở chế độ nhanh: mỗi pha một lượt nạp,
công tắc lỗi chắc chắn hỏng (fail_rate=1) để kết quả không phụ thuộc may rủi.
"""
import json
import os
import socket
import threading
import time
import urllib.request

import mongomock
import pytest
import uvicorn

from scenarios.ops import run as ops


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _mongomock_db():
    return mongomock.MongoClient(tz_aware=True).db, lambda: None


def _atlas_db():
    if os.getenv("SHIPAUDIT_SKIP_ATLAS") == "1":
        pytest.skip("SHIPAUDIT_SKIP_ATLAS=1")
    from pymongo import MongoClient

    from common import config

    client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=8_000)
    try:
        client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"không kết nối được MongoDB: {type(e).__name__}")
    db = client[f"{config.MONGO_DB}_smoke"]
    assert db.name.endswith("_smoke")

    def cleanup():
        for name in db.list_collection_names():
            db.drop_collection(name)
        client.close()

    cleanup_first = [db.drop_collection(n) for n in db.list_collection_names()]  # noqa: F841 - trạng thái sạch
    return db, cleanup


@pytest.fixture(params=["mongomock", "atlas"])
def server(request, tmp_path, monkeypatch, seed_rules):
    db, cleanup = _mongomock_db() if request.param == "mongomock" else _atlas_db()
    seed_rules(db)
    from app.deps import get_db
    from app.ingest import faults, pipeline
    from app.main import app

    monkeypatch.setattr(pipeline, "UPLOAD_DIR", tmp_path)
    monkeypatch.setenv("WEBHOOK_SECRET", "smoke-secret")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    faults.reset()
    app.dependency_overrides[get_db] = lambda: db
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert srv.started, "uvicorn không khởi động được"
    yield f"http://127.0.0.1:{port}", db
    srv.should_exit = True
    thread.join(timeout=10)
    app.dependency_overrides.clear()
    faults.reset()
    cleanup()


def test_ops_scenario_end_to_end_over_http(server, tmp_path):
    base, db = server
    api = ops.Api(base)
    lines = []
    report = ops.run(api, carrier="carrier_b", minutes=0, every=0, delay_ms=1_500, fail_rate=1.0,
                     out_dir=tmp_path, log=lines.append, sleep=lambda s: None)
    normal, incident, recovered = report["phases"]
    assert normal["by_http"] == {"201": 1} and recovered["by_http"] == {"201": 1}
    assert incident["by_http"] == {"503": 1} and incident["error_rate"] == 1.0
    assert incident["max_lag_seconds"] >= 1.5 and incident["max_lag_seconds"] > normal["max_lag_seconds"]
    assert json.loads((tmp_path / "ops-report.json").read_text(encoding="utf-8"))["phases"][1]["name"] == "su-co"

    # Trạng thái để lại: công tắc đã tắt, mỗi lượt nạp có một ingest_event, bảng kê nạp lại không nhân đôi.
    assert api._call("GET", "/admin/ingest-fault")[1] == {"delay_ms": 0, "fail_rate": 0.0}
    assert [e["status"] for e in db.ingest_events.find().sort("ts", 1)] == ["OK", "ERROR", "OK"]
    assert db.statement_lines.count_documents({}) == 4


def test_api_basics_over_http(server):
    base, _ = server
    api = ops.Api(base)
    status, health = api.health()
    assert status == 200 and health["status"] == "ok"
    assert api.upload("carrier_a", ops.SAMPLES / "statement_carrier_a.csv")[0] == 201
    status, recs = api._call("GET", "/reconciliations?carrier=carrier_a")
    assert status == 200 and recs["count"] >= 1
    req = urllib.request.Request(base + "/webhooks/datadog", data=b'{"alert_id": "x", "scope": "carrier:carrier_a"}',
                                 method="POST", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 401                                         # thiếu secret
    status, body = api._call("POST", "/webhooks/datadog",
                             json.dumps({"alert_id": "smoke-1", "alert_transition": "Recovered"}).encode(),
                             {"Content-Type": "application/json", "X-ShipAudit-Secret": "smoke-secret"})
    assert status == 200 and body["action"] == "ignored"
