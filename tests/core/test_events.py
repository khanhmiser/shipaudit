"""Test sự kiện Datadog cho thao tác claim (core/events.py), không gọi mạng."""
import json
import urllib.error

import pytest

from core import events

CLAIMS = [
    {"claim_id": "1", "carrier": "carrier_b", "amount": 150_000, "alert_id": "cycle-9"},
    {"claim_id": "2", "carrier": "carrier_b", "amount": 150_000, "alert_id": "cycle-9"},
    {"claim_id": "3", "carrier": "carrier_a", "amount": 40_000},
]


def test_one_event_per_carrier_with_count_and_amount(monkeypatch):
    monkeypatch.setenv("DD_ENV", "demo")
    got = events.claim_events("approved", CLAIMS, by="Kế toán Lan", names={"carrier_b": "Carrier B"})
    assert [e["title"] for e in got] == ["ShipAudit: Duyệt claim 1 claim · carrier_a",
                                         "ShipAudit: Duyệt claim 2 claim · Carrier B"]
    b = got[1]
    assert "Số tiền khiếu nại: 300.000đ" in b["text"] and "Người thao tác: Kế toán Lan" in b["text"]
    assert {"project:shipaudit", "carrier:carrier_b", "claim_action:approved", "env:demo", "alert_id:cycle-9"} <= set(b["tags"])
    assert b["alert_type"] == "info" and b["aggregation_key"] == "shipaudit-claims-carrier_b"


def test_recovered_shows_refund_and_success():
    got = events.claim_events("recovered", [{"carrier": "carrier_b", "amount": 150_000, "recovered_amount": 140_000}])
    assert got[0]["alert_type"] == "success" and "Hãng đã hoàn: 140.000đ" in got[0]["text"]
    with pytest.raises(ValueError):
        events.claim_events("deleted", CLAIMS)


def test_publish_is_off_unless_enabled(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "x")
    monkeypatch.delenv("SHIPAUDIT_DD_EVENTS", raising=False)
    assert events.publish("created", CLAIMS) == 0                       # chưa bật: không gửi gì
    monkeypatch.setenv("SHIPAUDIT_DD_EVENTS", "true")
    monkeypatch.delenv("DD_API_KEY")
    assert not events.enabled()                                          # bật mà thiếu khóa cũng không gửi
    assert events.publish("created", []) == 0


def test_sender_posts_each_event_and_survives_errors(monkeypatch, capsys):
    sent = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        sent.append((req.full_url, req.get_header("Dd-api-key"), json.loads(req.data)))
        return Resp()

    sender = events.DatadogEvents("secret-key", "uk1.datadoghq.com", opener=opener)
    assert events.publish("created", CLAIMS, source="datadog_webhook", sender=sender) == 2
    assert sent[0][0] == "https://api.uk1.datadoghq.com/api/v1/events" and sent[0][1] == "secret-key"
    assert "cảnh báo Datadog" in sent[1][2]["text"]

    def broken(req, timeout):
        raise urllib.error.URLError("down")

    assert events.publish("created", CLAIMS, sender=events.DatadogEvents("secret-key", opener=broken)) == 0
    err = capsys.readouterr().err
    assert "không gửi được" in err and "secret-key" not in err
