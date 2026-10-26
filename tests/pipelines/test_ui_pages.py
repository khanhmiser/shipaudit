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
