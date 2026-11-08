"""Test phần thuần của giao diện: định dạng tiền, thời gian, breakdown từng khoản (chạy offline)."""
from datetime import datetime, timedelta

from core.periods import VN_TZ
from ui import view

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=VN_TZ)

# Bản ghi đối soát thật trên dữ liệu seed: Carrier B trừ phí hoàn gấp đôi, không ghi riêng khoản trả trước.
REC_RETURN_DOUBLE = {
    "reconciliation_id": "STM-B-2026W40:B-001351",
    "diff_type": "RETURN_FEE_DOUBLE",
    "expected_amount": 166_000, "actual_amount": 124_000, "diff": 42_000,
    "breakdown": {
        "cod_collected": 232_000, "prepaid_by_shop": 18_000, "return_fee_paid_by_shop": 0,
        "shipping_fee": 42_000, "insurance_fee": 0, "return_shipping_fee": 42_000, "storage_fee": 0,
        "address_change_fee": 0, "inspection_fee": 0, "promotion": 0, "transfer_fee": 0,
    },
    "actual_breakdown": {"cod_collected": 232_000, "shipping_fee": 42_000, "return_shipping_fee": 84_000,
                         "storage_fee": 0, "net_paid": 124_000},
}


def _by_item(rows):
    return {r["Khoản"]: r for r in rows}


def test_vnd():
    assert view.vnd(1_234_567) == "1.234.567 ₫"
    assert view.vnd(0) == "0 ₫"
    assert view.vnd(-42_000) == "−42.000 ₫"
    assert view.vnd(None) == "—"
    assert view.signed_vnd(42_000) == "+42.000 ₫"
    assert view.signed_vnd(-5) == "−5 ₫"


def test_time_left():
    assert view.time_left(NOW + timedelta(days=2, hours=5, minutes=10), NOW) == "Còn 2 ngày 5 giờ"
    assert view.time_left(NOW + timedelta(hours=3, minutes=20), NOW) == "Còn 3 giờ 20 phút"
    assert view.time_left(NOW - timedelta(days=1, hours=2), NOW) == "Quá hạn 1 ngày 2 giờ"
    assert view.time_left(None, NOW) == "—"
    assert view.time_left_hours(1.5) == "Còn 1 giờ 30 phút"


def test_deadline_stored_as_naive_utc():
    # pymongo trả naive UTC: 02:00 UTC = 09:00 giờ Việt Nam.
    deadline = datetime(2026, 10, 22, 2, 0) + timedelta(hours=1)
    assert view.time_left(deadline, NOW) == "Còn 1 giờ 0 phút"
    assert view.dt_vn(deadline) == "22/10/2026 10:00"


def test_period_label():
    assert view.period_label("2026-W42") == "Tuần 42/2026 (12/10–18/10)"
    assert view.period_label(None) == "—"


def test_breakdown_rows_return_fee_double():
    rows = view.breakdown_rows(REC_RETURN_DOUBLE)
    items = _by_item(rows)
    assert items["Phí chuyển hoàn"] == {"Khoản": "Phí chuyển hoàn", "Cộng/Trừ": "−", "Phải nhận": 42_000,
                                        "Thực nhận": 84_000, "Chênh lệch": 42_000}
    assert items["Tiền thu hộ"]["Chênh lệch"] == 0
    # Hãng không ghi riêng khoản trả trước: để trống, phần còn lại hiện ở dòng riêng.
    assert items["Doanh nghiệp trả trước"]["Thực nhận"] is None
    assert items[view.UNREPORTED]["Thực nhận"] == 18_000
    assert rows[-1] == {"Khoản": view.TOTAL, "Cộng/Trừ": "=", "Phải nhận": 166_000, "Thực nhận": 124_000,
                        "Chênh lệch": 42_000}
    assert "Phí bảo hiểm" not in items  # khoản bằng 0 ẩn mặc định


def test_breakdown_rows_sum_to_totals():
    """Cộng theo dấu các dòng ra đúng tổng phải nhận và thực nhận; chênh lệch từng khoản cộng lại khớp tổng."""
    rows = view.breakdown_rows(REC_RETURN_DOUBLE, include_zero=True)
    assert len(rows) == len(view.FORMULA_ITEMS) + 2
    sign = {"+": 1, "−": -1}
    body, total = rows[:-1], rows[-1]
    assert sum(sign[r["Cộng/Trừ"]] * (r["Phải nhận"] or 0) for r in body) == total["Phải nhận"]
    assert sum(sign[r["Cộng/Trừ"]] * (r["Thực nhận"] or 0) for r in body) == total["Thực nhận"]


def test_breakdown_rows_missing_in_statement():
    rec = {"diff_type": "MISSING_IN_STATEMENT", "expected_amount": 150_000, "actual_amount": 0, "diff": 150_000,
           "breakdown": {"cod_collected": 180_000, "shipping_fee": 30_000}}
    rows = view.breakdown_rows(rec)
    assert all(r["Thực nhận"] is None for r in rows[:-1])
    assert rows[-1]["Thực nhận"] == 0 and rows[-1]["Chênh lệch"] == 150_000
    assert view.UNREPORTED not in _by_item(rows)


def test_carrier_colors_follow_carrier_not_filter():
    names = {"carrier_c": "Carrier C", "carrier_a": "Carrier A", "carrier_b": "Carrier B"}
    domain, colors = view.carrier_colors(names)
    assert domain == ["Carrier A", "Carrier B", "Carrier C"]
    assert colors == list(view.SERIES_COLORS[:3])


def test_rows_use_labels_and_integer_money():
    names = {"carrier_b": "Carrier B"}
    rec = {**REC_RETURN_DOUBLE, "order_code": "B-001351", "carrier": "carrier_b", "statement_id": "STM-B-2026W40",
           "period": "2026-W40", "order_status": "RETURN_BY_CUSTOMER", "claim_deadline_at": NOW + timedelta(days=1)}
    row = view.reconciliation_rows([rec], names, NOW)[0]
    assert row["Hãng"] == "Carrier B"
    assert row["Loại chênh lệch"] == "Phí hoàn lệch / trừ hai lần"
    assert row["Trạng thái đơn"] == "Trả hàng"
    assert row["Còn lại"] == "Còn 1 ngày 0 giờ"
    assert all(type(row[k]) is int for k in ("Phải nhận", "Thực nhận", "Chênh lệch"))
