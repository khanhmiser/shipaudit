"""Chạy thử các trang Streamlit (AppTest) trên dữ liệu seed ở Mongo thật, vì các trang gọi pipeline
($facet, $lookup, $setWindowFields) mà mongomock không có. Kiểm tra trang chạy không lỗi và luồng
tạo claim nháp → duyệt claim ghi đúng vào `claims`.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from common import config
from common.enums import Collections
from core.periods import to_db

UI = Path(__file__).resolve().parents[2] / "ui"
PAGES = sorted((UI / "screens").glob("*.py"))


@pytest.fixture
def ui_env(seeded, now, monkeypatch):
    db, _ = seeded
    monkeypatch.setattr(config, "MONGO_DB", db.name)
    monkeypatch.setenv("SHIPAUDIT_NOW", now.isoformat())
    before = {c["claim_id"] for c in db[Collections.CLAIMS].find({}, {"claim_id": 1})}
    yield db
    db[Collections.CLAIMS].delete_many({"claim_id": {"$nin": list(before)}})


def _page_title(at: AppTest) -> str:
    """Tiêu đề trang: st.title (trang cũ) hoặc thẻ h1 trong đầu trang HTML theo bản thiết kế."""
    if at.title:
        return at.title[0].value
    for el in at.html:
        if 'class="sa-h1' in el.value:
            return el.value.split('class="sa-h1', 1)[1].split(">", 1)[1].split("<", 1)[0]
    return ""


def _run(path: Path, **state) -> AppTest:
    at = AppTest.from_file(str(path), default_timeout=90)
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def test_app_router_runs(ui_env):
    at = _run(UI / "app.py")
    assert not at.exception
    assert _page_title(at) == "Tổng quan đối soát"


@pytest.mark.parametrize("page", PAGES, ids=[p.stem for p in PAGES])
def test_page_runs_without_error(ui_env, page):
    at = _run(page)
    assert not at.exception, [e.message for e in at.exception]
    assert _page_title(at)


def test_draft_then_approve_claim(ui_env, now):
    db = ui_env
    rec = db[Collections.RECONCILIATIONS].find_one(
        {"diff": {"$gt": 0}, "diff_type": {"$ne": "NONE"}, "claim_deadline_at": {"$gt": to_db(now)}},
        sort=[("reconciliation_id", 1)],
    )
    assert rec is not None
    rid = rec["reconciliation_id"]
    db[Collections.CLAIMS].delete_many({"reconciliation_id": rid})

    at = _run(UI / "screens" / "2_Chi_tiet_don.py", order_code=rec["order_code"])
    assert not at.exception
    at.button(key=f"draft_{rid}").click().run()
    assert not at.exception
    claim = db[Collections.CLAIMS].find_one({"reconciliation_id": rid})
    assert claim["status"] == "DRAFT" and claim["amount"] == rec["diff"] and claim["source"] == "manual"

    at = _run(UI / "screens" / "5_Claims.py")
    at.selectbox(key="cl_pick").set_value(claim["claim_id"]).run()
    at.button(key="approve").click().run()  # chưa ghi tên người duyệt: không được duyệt
    assert db[Collections.CLAIMS].find_one({"claim_id": claim["claim_id"]})["status"] == "DRAFT"
    assert at.error

    at.text_input(key="cl_person").input("Người duyệt thử").run()
    at.button(key="approve").click().run()
    assert not at.exception
    approved = db[Collections.CLAIMS].find_one({"claim_id": claim["claim_id"]})
    assert approved["status"] == "APPROVED" and approved["approved_by"] == "Người duyệt thử"


def test_bulk_approve_drafts(ui_env, now):
    from core.claims import ClaimService

    db = ui_env
    recs = list(db[Collections.RECONCILIATIONS].find(
        {"diff": {"$gt": 0}, "diff_type": {"$ne": "NONE"}, "claim_deadline_at": {"$gt": to_db(now)}},
        sort=[("reconciliation_id", -1)], limit=2,
    ))
    assert len(recs) == 2
    for r in recs:
        db[Collections.CLAIMS].delete_many({"reconciliation_id": r["reconciliation_id"]})
    svc = ClaimService(db, now=lambda: now)
    ids = [svc.create_draft(r["reconciliation_id"], "manual")["claim_id"] for r in recs]

    at = _run(UI / "screens" / "5_Claims.py")
    at.multiselect(key="bulk_pick").set_value(ids).run()
    at.text_input(key="bulk_person").input("Người duyệt hàng loạt").run()
    at.button(key="bulk_approve").click().run()
    assert not at.exception
    got = {c["claim_id"]: c for c in db[Collections.CLAIMS].find({"claim_id": {"$in": ids}})}
    assert all(c["status"] == "APPROVED" and c["approved_by"] == "Người duyệt hàng loạt" for c in got.values())


WRITE_KEYS = {"expire", "bulk_approve", "bulk_recover", "approve", "submit", "recover", "reject",
              "draft_chosen", "draft_all"}


def test_read_only_hides_every_write_action(ui_env, now, monkeypatch):
    """Bản demo cho giám khảo (SHIPAUDIT_READ_ONLY=true): trang vẫn chạy, không còn nút ghi dữ liệu nào."""
    db = ui_env
    rec = db[Collections.RECONCILIATIONS].find_one({"diff": {"$gt": 0}, "diff_type": {"$ne": "LATE_PAYOUT"},
                                                    "claim_deadline_at": {"$gt": to_db(now)}})
    from core.claims import ClaimService
    ClaimService(db, now=lambda: now).create_draft(rec["reconciliation_id"], "manual")   # để trang Claims có claim
    monkeypatch.setenv("SHIPAUDIT_READ_ONLY", "true")
    for page in PAGES:
        state = {"order_code": rec["order_code"]} if page.stem == "2_Chi_tiet_don" else {}
        at = _run(page, **state)
        assert not at.exception, (page.stem, [e.message for e in at.exception])
        keys = {b.key for b in at.button} | {b.key for b in at.get("download_button") if hasattr(b, "key")}
        assert not (keys & WRITE_KEYS), (page.stem, keys & WRITE_KEYS)
        assert not any((b.key or "").startswith("draft_") for b in at.button), page.stem


def test_streamlit_secrets_become_env(ui_env):
    """Streamlit Community Cloud: secrets cấp gốc thành biến môi trường trước khi trang đọc cấu hình."""
    import os
    os.environ.pop("SHIPAUDIT_READ_ONLY", None)
    try:
        at = AppTest.from_file(str(UI / "app.py"), default_timeout=90)
        at.secrets["SHIPAUDIT_READ_ONLY"] = "true"
        at.run()
        assert not at.exception, [e.message for e in at.exception]
        assert os.environ.get("SHIPAUDIT_READ_ONLY") == "true"
        assert any("Bản demo chỉ xem" in i.value for i in at.sidebar.info)
    finally:
        os.environ.pop("SHIPAUDIT_READ_ONLY", None)


def test_rejected_claim_followup_on_claims_page(ui_env, now):
    """Claim bị hãng từ chối: trang Claims hiện lý do, ghi được nhật ký theo dõi; Tổng quan có thẻ theo dõi."""
    from core.claims import ClaimService
    db = ui_env
    rec = db[Collections.RECONCILIATIONS].find_one({"diff": {"$gt": 0}, "diff_type": {"$ne": "LATE_PAYOUT"},
                                                    "claim_deadline_at": {"$gt": to_db(now)}})
    svc = ClaimService(db, now=lambda: now)
    c = svc.create_draft(rec["reconciliation_id"], "manual")
    svc.approve(c["claim_id"], "Kế toán Lan")
    svc.submit(c["claim_id"], "Kế toán Lan")
    svc.mark_rejected(c["claim_id"], "Kế toán Lan", "thiếu ảnh biên nhận")

    at = _run(UI / "screens" / "5_Claims.py", cl_status="REJECTED", cl_pick=c["claim_id"])
    assert not at.exception, [e.message for e in at.exception]
    assert any("thiếu ảnh biên nhận" in w.value for w in at.warning)
    at.text_input(key="cl_person").set_value("Kế toán Lan")
    at.text_area(key="rej_fu_note").set_value("Đã gọi hãng, gửi lại ảnh biên nhận")
    at.run()
    at.button(key="rej_fu_save").click().run()
    assert not at.exception, [e.message for e in at.exception]
    saved = db[Collections.CLAIMS].find_one({"claim_id": c["claim_id"]})
    assert saved["status"] == "REJECTED" and saved["followups"][-1]["note"] == "Đã gọi hãng, gửi lại ảnh biên nhận"

    overview = _run(UI / "screens" / "0_Tong_quan.py")
    assert not overview.exception
    assert any("Bị từ chối, đang theo dõi" in h.value for h in overview.html)
