"""Worker change stream: hàm xử lý từng sự kiện và vòng lặp tự thử lại khi mất kết nối."""
import json
import logging
import threading

from pymongo.errors import AutoReconnect, OperationFailure

from app.telemetry.logging import JsonFormatter
from app.workers import change_stream as cs


def _rec(**kw):
    return {"statement_id": "STM-B-2026W42", "order_code": "B-1", "carrier": "carrier_b",
            "diff": 42000, "diff_type": "RETURN_FEE_DOUBLE", **kw}


def test_insert_with_diff_logs_and_counts(caplog):
    calls = []
    with caplog.at_level(logging.INFO, logger="shipaudit.worker"):
        event = cs.handle_change({"operationType": "insert", "fullDocument": _rec()},
                                 emit=lambda *a: calls.append(a))
    assert event["carrier"] == "carrier_b" and event["order_code"] == "B-1" and event["diff"] == 42000
    assert event["trace_id"]
    assert calls == [("shipaudit.ops.reconciliation_diff_events", 1,
                      {"carrier": "carrier_b", "diff_type": "RETURN_FEE_DOUBLE"})]
    line = json.loads(JsonFormatter().format(caplog.records[-1]))  # dòng log JSON có đủ trường
    for key in ("trace_id", "carrier", "order_code", "diff"):
        assert line[key] == event[key]


def test_negative_diff_also_logged():
    assert cs.handle_change({"operationType": "replace", "fullDocument": _rec(diff=-500)}, emit=lambda *a: None)


def test_zero_diff_or_unchanged_update_ignored():
    calls = []

    def emit(*a):
        calls.append(a)

    assert cs.handle_change({"operationType": "insert", "fullDocument": _rec(diff=0, diff_type="NONE")}, emit) is None
    # Đối soát lại, chỉ updated_at đổi: không ghi lại.
    assert cs.handle_change({"operationType": "update", "fullDocument": _rec(),
                             "updateDescription": {"updatedFields": {"updated_at": 1}}}, emit) is None
    assert cs.handle_change({"operationType": "update", "fullDocument": _rec(),
                             "updateDescription": {"updatedFields": {"diff": 42000}}}, emit)
    assert len(calls) == 1


class FakeStream:
    """Trả lần lượt các sự kiện; hết sự kiện thì bật `stop` để vòng lặp dừng."""

    def __init__(self, changes, stop, token):
        self.changes, self.stop, self.resume_token, self.alive = list(changes), stop, token, True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def try_next(self):
        if not self.changes:
            self.stop.set()
            return None
        item = self.changes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeColl:
    def __init__(self, script, stop):
        self.script, self.stop, self.resume_args = list(script), stop, []

    def watch(self, pipeline, **kw):
        self.resume_args.append(kw.get("resume_after"))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        changes, token = step
        return FakeStream(changes, self.stop, token)


def test_run_retries_and_resumes():
    stop = threading.Event()
    insert = {"operationType": "insert", "fullDocument": _rec()}
    coll = FakeColl([
        AutoReconnect("mạng chập chờn"),                                # mở stream lỗi
        AutoReconnect("vẫn lỗi"),                                       # lỗi lần nữa: chờ lâu hơn
        ([insert, AutoReconnect("rớt giữa chừng")], {"_data": "T1"}),  # nhận 1 sự kiện rồi rớt
        ([insert], {"_data": "T2"}),                                    # nối lại từ T1
    ], stop)
    sleeps, emitted = [], []
    cs.run({"reconciliations": coll}, stop=stop, sleep=sleeps.append, emit=lambda *a: emitted.append(a[0]))
    assert coll.resume_args == [None, None, None, {"_data": "T1"}]
    assert sleeps == [1.0, 2.0, 1.0]  # lỗi liên tiếp thì chờ lâu dần; mở lại được thì tính lại từ đầu
    assert emitted.count("shipaudit.ops.reconciliation_diff_events") == 2
    assert emitted.count("shipaudit.ops.change_stream_errors") == 3


def test_run_drops_stale_resume_token():
    stop = threading.Event()
    coll = FakeColl([
        ([OperationFailure("history lost", code=286)], {"_data": "OLD"}),
        ([], None),
    ], stop)
    cs.run({"reconciliations": coll}, stop=stop, sleep=lambda s: None, emit=lambda *a: None)
    assert coll.resume_args == [None, None]
