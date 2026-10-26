"""Phần thuần của màn Chênh lệch (ui/cases.py) và Chi tiết đơn (ui/detail.py), không cần Streamlit hay Mongo."""
from datetime import datetime, timedelta, timezone

from core.rules import CarrierRule
from ui import cases, detail

NOW = datetime(2026, 10, 23, 1, 0, tzinfo=timezone.utc)


def rec(code="A-1", diff=60_000, kind="FEE_MISMATCH", hours=20, **kw):
    base = {
        "reconciliation_id": f"ST-A-2026W42:{code}", "statement_id": "ST-A-2026W42", "order_code": code,
        "carrier": "carrier_a", "period": "2026-W42", "diff_type": kind, "diff": diff,
        "expected_amount": 593_500, "actual_amount": 593_500 - diff,
        "claim_deadline_at": NOW + timedelta(hours=hours),
        "breakdown": {"cod_collected": 650_000, "shipping_fee": 50_000, "transfer_fee": 6_500},
        "actual_breakdown": {"cod_collected": 650_000, "shipping_fee": 50_000 + diff, "transfer_fee": 6_500,
                             "net_paid": 593_500 - diff},
    }
    return {**base, **kw}


RULE = CarrierRule.from_doc({
    "carrier": "carrier_a", "display_name": "Carrier A", "dim_weight_divisor": 6000, "cod_payout_days": 2,
    "claim_window_hours": 72,
    "rate_table": [{"region": "noi_vung", "brackets": [{"max_weight_g": 500, "fee": 28_000}],
                    "extra_step_g": 500, "extra_fee": 4_500}],
})


def test_tabs_are_filters_by_deadline_and_claim_status():
    recs = [rec("A-1", hours=20), rec("A-2", hours=200), rec("A-3", hours=-5), rec("A-4", diff=0, kind="LATE_PAYOUT"),
            rec("A-5", hours=30)]
    claims = {"ST-A-2026W42:A-5": {"status": "SUBMITTED"}, "ST-A-2026W42:A-2": {"status": "RECOVERED"}}
    counts = cases.tab_counts(recs, claims, NOW)
    assert counts == {"all": 5, "soon": 1, "claiming": 1, "recovered": 1}
    assert [r["order_code"] for r in sorted(recs, key=lambda r: cases.priority(r, NOW))][:3] == ["A-1", "A-5", "A-2"]


def test_case_table_escapes_and_links_order():
    html = cases.case_table([rec("<b>x")], {"carrier_a": "Carrier A"}, {}, NOW)
    assert "&lt;b&gt;x" in html and "<b>x" not in html
    assert 'href="chi-tiet-don?order=' in html and "Nghiêm trọng" in html


def test_type_bars_sum_by_type_largest_first():
    bars = cases.type_bars([rec("A-1", diff=10_000), rec("A-2", diff=50_000, kind="COD_MISMATCH"), rec("A-3", diff=5_000)])
    assert [(b["diff_type"], b["count"], b["amount"]) for b in bars] == [("COD_MISMATCH", 1, 50_000), ("FEE_MISMATCH", 2, 15_000)]


def test_breakdown_table_highlights_mismatched_item_and_total():
    html = detail.breakdown_table(rec())
    assert 'class="sa-hl"' in html and 'class="sa-total"' in html
    assert "−50.000" in html and "−110.000" in html and "+60.000" in html


def test_why_diff_names_item_and_rule_derivation():
    order = {"carrier": "carrier_a", "region": "noi_vung", "weight_g": 400, "length_cm": 30, "width_cm": 20,
             "height_cm": 10, "status": "DELIVERED"}
    why = detail.why_diff(rec(), order, RULE, {"carrier_a": "Carrier A"})
    assert "Phí giao hàng: quy tắc 50.000 ₫, hãng ghi 110.000 ₫" in why["lines"][0]
    assert why["pair"] == [("Phí giao hàng", 50_000, 110_000)]
    assert "1.000 g (quy đổi: 30×20×10 cm ÷ 6.000)" in why["note"]


def test_why_diff_merged_return_fee_and_missing():
    merged = rec(kind="RETURN_FEE_DOUBLE", diff=14_500,
                 breakdown={"shipping_fee": 29_000, "return_shipping_fee": 14_500},
                 actual_breakdown={"shipping_fee": 58_000, "net_paid": -29_000})
    # Hãng gộp phí: so trên phí giao hàng đã gộp (29.000 + 14.500 = 43.500) với 58.000 hãng ghi
    why = detail.why_diff(merged, None, None)
    assert "gộp phí chuyển hoàn" in why["lines"][0] and "14.500" in why["lines"][0]
    assert why["pair"] == [("Phí giao hàng (gộp phí chuyển hoàn)", 43_500, 58_000)]
    table = detail.breakdown_table(merged)
    assert "Phí giao hàng (gộp)" in table and "hãng gộp cả phí chuyển hoàn" in table and "+14.500" in table
    assert "Phí chuyển hoàn<" not in table
    assert "Phí giao hàng (gộp)" in detail.why_html(why)
    missing = rec(kind="MISSING_IN_STATEMENT", actual_breakdown=None, actual_amount=0)
    assert "không có dòng nào" in detail.why_diff(missing, None, None)["lines"][0]


def test_claim_message_and_recovery_steps():
    r = rec()
    msg = detail.claim_message(r, detail.why_diff(r, None, None), "Carrier A")
    assert msg.startswith("Kính gửi Carrier A") and "Chênh lệch: 60.000 ₫" in msg and "A-1" in msg
    states = [s["state"] for s in detail.recovery_steps(r, {"status": "SUBMITTED"})]
    assert states == ["done", "done", "done", "now", "wait"]
    assert len(detail.recovery_steps(rec(diff=0, kind="NONE"), None)) == 1


def test_timeline_is_sorted_and_marks_deadline():
    r = rec(updated_at=NOW - timedelta(hours=1))
    ev = detail.timeline_events(r, {"delivered_at": NOW - timedelta(days=3), "status": "DELIVERED"},
                                [{"statement_id": "ST-A-2026W42", "ingested_at": NOW - timedelta(hours=2), "net_paid": 1}],
                                {"history": [{"status": "DRAFT", "at": NOW, "by": "manual"}]}, NOW)
    assert [e["badge"] for e in ev] == ["Đơn", "Bảng kê", "Đối soát", "Claim", "Hạn khiếu nại"]
    assert "<script>" not in detail.timeline_html([{**ev[0], "text": "<script>"}])


def test_merged_fee_mismatch_reports_only_the_real_gap():
    # Carrier C, đơn hoàn: quy tắc 61.000 + bảo hiểm 3.600 + phí hoàn 30.500 = 95.100; hãng ghi tổng 101.600
    r = rec(kind="FEE_MISMATCH", diff=6_500, expected_amount=-95_100, actual_amount=-101_600,
            breakdown={"shipping_fee": 61_000, "insurance_fee": 3_600, "return_shipping_fee": 30_500},
            actual_breakdown={"cod_collected": 0, "shipping_fee": 101_600, "net_paid": -101_600})
    why = detail.why_diff(r, None, None)
    assert why["lines"] == ["Phí giao hàng (gộp phí bảo hiểm, phí chuyển hoàn): quy tắc 95.100 ₫, hãng ghi 101.600 ₫ "
                            "(doanh nghiệp nhận thiếu 6.500 ₫)."]
