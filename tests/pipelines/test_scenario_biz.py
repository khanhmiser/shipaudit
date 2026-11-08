"""Test kịch bản lớp nghiệp vụ (B10) chạy trọn trên MongoDB thật, chế độ nhanh (không chờ, không gửi Datadog).

Database riêng `<MONGO_DB>_test_scn` (kịch bản xóa và seed lại, không dùng chung với fixture `seeded`).
"""
import os

import pytest
from pymongo import MongoClient

from common import config
from common.enums import Collections
from scenarios.biz import run as scenario


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    if os.getenv("SHIPAUDIT_SKIP_ATLAS") == "1":
        pytest.skip("SHIPAUDIT_SKIP_ATLAS=1")
    client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=8_000)
    try:
        client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"không kết nối được MongoDB: {type(e).__name__}")
    db = client[f"{config.MONGO_DB}_test_scn"]
    assert db.name.endswith("_test_scn")
    sent = []
    out = tmp_path_factory.mktemp("scenario")
    rep = scenario.run(db, metric=lambda n, v, t=None: sent.append((n, v, t)), hold_minutes=0,
                       approve_by="test-nguoi-duyet", recover_by="test-ke-toan", out_dir=out, log=lambda s: None, sleep=lambda s: None)
    yield {"report": rep, "db": db, "sent": sent, "out": out}
    for name in db.list_collection_names():
        db.drop_collection(name)
    client.close()


def _phase(rep, prefix):
    return next(p for p in rep["phases"] if p["name"].startswith(prefix))


def test_baseline_is_quiet(report):
    p = _phase(report["report"], "1.")
    assert all(s == {"threshold": "OK", "deadline": "OK"} for s in p["monitors"].values()), p["monitors"]
    assert p["summary"]["carrier_b"]["open_amount"] == 0          # bảng kê W42 của B chưa về


def test_incident_is_fully_detected(report):
    inc = report["report"]["incident"]
    assert len(inc["changed"]) == scenario.ERRORS
    assert inc["detected"] == {code: "COD_MISMATCH" for code in inc["changed"]}   # phát hiện đủ 100%


def test_incident_triggers_threshold_then_deadline(report):
    rep = report["report"]
    p2, p3 = _phase(rep, "2."), _phase(rep, "3.")
    assert p2["monitors"]["carrier_b"] == {"threshold": "ALERT", "deadline": "OK"}
    added = scenario.ERRORS * scenario.SHORTFALL
    assert p2["summary"]["carrier_b"]["open_amount"] >= added
    assert p3["monitors"]["carrier_b"] == {"threshold": "ALERT", "deadline": "ALERT"}
    assert p3["summary"]["carrier_b"]["claim_hours_left"] == pytest.approx(21, abs=0.01)
    # Hãng khác không bị kéo theo.
    for carrier in ("carrier_a", "carrier_c"):
        assert p3["monitors"][carrier] == {"threshold": "OK", "deadline": "OK"}


def test_webhook_is_idempotent_and_claims_resolve(report):
    rep, db = report["report"], report["db"]
    claims = rep["claims"]
    assert claims["drafts"] == claims["drafts_on_retry"] == p3_open_count(rep) > 0
    assert claims["not_submitted"] == 0
    assert db[Collections.CLAIMS].count_documents({"alert_id": claims["alert_id"]}) == claims["drafts"]
    assert db[Collections.CLAIMS].count_documents({"status": "RECOVERED"}) == claims["drafts"]   # pha 5: hãng đã hoàn tiền
    assert all(c["source"] == "datadog_webhook" for c in db[Collections.CLAIMS].find())
    p4a, p4b = _phase(rep, "4a."), _phase(rep, "4b.")
    assert p4a["monitors"]["carrier_b"]["deadline"] == "ALERT"    # claim nháp chưa phải đã xử lý
    assert p4b["monitors"]["carrier_b"] == {"threshold": "OK", "deadline": "OK"}
    assert p4b["summary"]["carrier_b"]["open_amount"] == 0


def p3_open_count(rep):
    return _phase(rep, "3.")["summary"]["carrier_b"]["open_count"]


def test_metrics_emitted_each_phase_and_outputs_written(report):
    names = {n for n, _, _ in report["sent"]}
    assert names == {"shipaudit.biz.diff_amount", "shipaudit.biz.diff_count", "shipaudit.biz.claim_hours_left",
                    "shipaudit.biz.claim_amount", "shipaudit.biz.recovered_amount"}
    per_round = len(report["sent"]) // len(report["report"]["phases"])
    assert per_round * len(report["report"]["phases"]) == len(report["sent"])
    csv = (report["out"] / "STM-B-2026W42.csv").read_text(encoding="utf-8")
    assert csv.splitlines()[0] == "ma_don;thu_ho;cuoc_van_chuyen;phi_hoan;phi_luu_kho;thuc_tra"
    assert (report["out"] / "biz-report.json").exists()


def test_monitor_states_rules():
    th = scenario.load_thresholds()
    s = {"x": {"open_amount": 15_000_001, "claim_hours_left": 23.9},
         "y": {"open_amount": 10_000_001, "claim_hours_left": 47.9},
         "z": {"open_amount": 10_000_000, "claim_hours_left": 48}}
    assert scenario.monitor_states(s, th) == {
        "x": {"threshold": "ALERT", "deadline": "ALERT"},
        "y": {"threshold": "WARN", "deadline": "WARN"},
        "z": {"threshold": "OK", "deadline": "OK"},
    }


def test_carrier_refund_phase_recovers_submitted_claims(report):
    rep = report["report"]
    rec = rep["claims"]["recovered"]
    assert rec["claims"] == rep["claims"]["drafts"] and rec["amount"] > 0 and rec["still_waiting"] == 0
    phase = _phase(rep, "5.")
    assert phase["summary"]["carrier_b"]["open_amount"] == 0
    names = {n for n, _, _ in report["sent"]}
    assert {"shipaudit.biz.claim_amount", "shipaudit.biz.recovered_amount"} <= names
    recovered = [v for n, v, t in report["sent"] if n == "shipaudit.biz.recovered_amount" and t["carrier"] == "carrier_b"]
    assert recovered[-1] == rec["amount"]
