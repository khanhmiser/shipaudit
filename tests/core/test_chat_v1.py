"""Bộ dữ liệu chat_v1: chuyển định dạng, quy tắc hãng mới (làm tròn, phí hoàn cố định theo vùng, kỳ trả tiền
tính từ cuối kỳ) và golden test với labels.json (đáp án của bộ)."""
from datetime import datetime, timezone

import mongomock
import pytest

from common.enums import DiffType
from core.money import apply_bp
from core.reconcile import reconcile_statement
from core.rules import CarrierRule, RuleError
from generator import chat_v1

SRC = chat_v1.SRC_DIR
needs_data = pytest.mark.skipif(not (SRC / "labels.json").exists(), reason="chưa có generator/out/chat_v1")
NOW = datetime(2026, 10, 23, 1, 0, tzinfo=timezone.utc)


def rule_doc(**over) -> dict:
    doc = {
        "carrier": "carrier_a", "version": 1, "dim_weight_divisor": 6000,
        "rate_table": [
            {"region": "noi_tinh", "brackets": [{"max_weight_g": 500, "fee": 22_000}], "extra_step_g": 500, "extra_fee": 3_000},
            {"region": "noi_vung", "brackets": [{"max_weight_g": 500, "fee": 28_000}], "extra_step_g": 500, "extra_fee": 4_500},
        ],
        "surcharges": {
            "insurance": {"rate_bp": 50, "min_declared_value": 1_000_000, "round_unit": 100, "round_mode": "half_even"},
            "return": {"rate_bp": 5_000, "fixed": 0, "round_unit": 500, "round_mode": "half_even",
                       "flat_by_region": {"noi_tinh": 5_000}},
        },
        "transfer_fee": 1_650, "cod_payout_days": 2, "claim_window_hours": 72,
        "payout_basis": "period_end",
        "status_policy": {
            "DELIVERED": {"collect_cod": True, "charge_shipping": True, "charge_return": False},
            "RETURNED": {"collect_cod": False, "charge_shipping": True, "charge_return": True},
            "LOST": {"collect_cod": False, "charge_shipping": False, "charge_return": False},
        },
    }
    doc.update(over)
    return doc


# ── Quy tắc hãng mới ──
def test_half_even_rounding_to_unit():
    # 2.770.000 × 0,5% = 13.850: half-even về bội số 100 là 13.800, half-up là 13.900
    assert apply_bp(2_770_000, 50, 100, "half_even") == 13_800
    assert apply_bp(2_770_000, 50, 100, "half_up") == 13_900
    assert apply_bp(2_770_000, 50) == 13_850  # mặc định không đổi: về 1đ


def test_rule_rounding_and_flat_return_by_region():
    rule = CarrierRule.from_doc(rule_doc())
    assert rule.insurance_fee(2_770_000) == 13_800
    assert rule.return_shipping_fee(38_500, "noi_vung") == 19_000  # 19.250 → bội số 500 half-even
    assert rule.return_shipping_fee(49_500, "noi_vung") == 25_000  # 24.750 → 25.000
    assert rule.return_shipping_fee(28_000, "noi_tinh") == 5_000   # cố định thay cho 50%
    assert rule.return_shipping_fee(28_000) == 14_000              # không biết vùng thì theo %


def test_rule_rejects_bad_new_params():
    with pytest.raises(RuleError, match="payout_basis"):
        CarrierRule.from_doc(rule_doc(payout_basis="tuy_y"))
    bad = rule_doc()
    bad["surcharges"]["return"]["round_mode"] = "ceil"
    with pytest.raises(RuleError, match="round_mode"):
        CarrierRule.from_doc(bad)
    bad = rule_doc()
    bad["surcharges"]["return"]["flat_by_region"] = {"vung_la": 1}
    with pytest.raises(RuleError, match="vùng lạ"):
        CarrierRule.from_doc(bad)


def test_payout_basis_period_end_vs_delivered_plus_days():
    delivered = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)  # thứ Năm tuần 35
    by_end = CarrierRule.from_doc(rule_doc())
    assert by_end.statement_period(delivered) == "2026-W35"
    assert by_end.payout_due(delivered).isoformat() == "2026-09-02T00:00:00+07:00"  # cuối kỳ + 2 ngày
    start, end = by_end.delivery_window("2026-W35")
    assert (end - start).days == 7 and start.isoformat() == "2026-08-24T00:00:00+07:00"

    plus = CarrierRule.from_doc(rule_doc(payout_basis="delivered_plus_days"))
    assert plus.statement_period(delivered) == "2026-W35"
    assert plus.delivery_window("2026-W35")[0].isoformat() == "2026-08-22T00:00:00+07:00"  # lùi 2 ngày


# ── Đối soát: đơn trả muộn và đơn thất lạc ──
def _db():
    db = mongomock.MongoClient()["t"]
    db.carrier_rules.insert_one(rule_doc())
    return db


def _order(code, status="DELIVERED", delivered="2026-08-25T03:00:00", **kw):
    o = {"order_code": code, "carrier": "carrier_a", "region": "noi_vung", "weight_g": 400, "cod_amount": 100_000,
         "declared_value": 100_000, "prepaid_by_shop": 0, "status": status}
    if delivered:
        o["delivered_at"] = datetime.fromisoformat(delivered)
    return {**o, **kw}


def _line(sid, code, period, net, **kw):
    return {"statement_id": sid, "carrier": "carrier_a", "order_code": code, "period": period,
            "cod_collected": 100_000, "shipping_fee": 28_000, "storage_fee": 0, "address_change_fee": 0,
            "inspection_fee": 0, "promotion": 0, "transfer_fee": 1_650, "net_paid": net,
            "ingested_at": datetime(2026, 9, 1, 2, 0), **kw}


def test_late_order_is_not_missing_when_it_arrives_in_later_statement():
    db = _db()
    db.orders.insert_many([_order("A-1"), _order("A-2")])
    db.statement_lines.insert_many([
        _line("ST-A-W35", "A-2", "2026-W35", 70_350),
        _line("ST-A-W36", "A-1", "2026-W36", 70_350),  # A-1 giao tuần 35, về ở bảng kê tuần 36
    ])
    r35 = {r["order_code"]: r for r in reconcile_statement("ST-A-W35", db, now=NOW)}
    assert set(r35) == {"A-2"}  # A-1 không bị báo thiếu vì đã có ở kỳ sau
    r36 = reconcile_statement("ST-A-W36", db, now=NOW)
    assert [(r["order_code"], r["diff_type"]) for r in r36] == [("A-1", DiffType.LATE_PAYOUT.value)]


def test_real_time_arrival_settles_earlier_missing_record():
    db = _db()
    db.orders.insert_many([_order("A-1"), _order("A-2")])
    db.statement_lines.insert_one(_line("ST-A-W35", "A-2", "2026-W35", 70_350))
    first = {r["order_code"]: r["diff_type"] for r in reconcile_statement("ST-A-W35", db, now=NOW)}
    assert first["A-1"] == DiffType.MISSING_IN_STATEMENT.value  # lúc đó đúng là chưa thấy tiền

    db.statement_lines.insert_one(_line("ST-A-W36", "A-1", "2026-W36", 70_350))
    reconcile_statement("ST-A-W36", db, now=NOW)
    assert db.reconciliations.count_documents({"order_code": "A-1", "diff_type": "MISSING_IN_STATEMENT"}) == 0

    # đã có claim cho bản ghi thiếu thì giữ lại, chỉ đánh dấu đã về muộn
    db.statement_lines.insert_one(_line("ST-A-W35", "A-3", "2026-W35", 70_350))
    db.orders.insert_one(_order("A-4"))
    db.statement_lines.insert_one(_line("ST-A-W36", "A-5", "2026-W36", 70_350))
    db.orders.insert_one(_order("A-5"))
    db.orders.insert_one(_order("A-3"))
    reconcile_statement("ST-A-W35", db, now=NOW)
    rid = "ST-A-W35:A-4"
    db.claims.insert_one({"reconciliation_id": rid, "status": "DRAFT"})
    db.statement_lines.insert_one(_line("ST-A-W36", "A-4", "2026-W36", 70_350))
    reconcile_statement("ST-A-W36", db, now=NOW)
    kept = db.reconciliations.find_one({"reconciliation_id": rid})
    assert kept is not None and kept["arrived_late"] is True


def test_lost_order_without_row_is_not_reported_missing():
    db = _db()
    db.orders.insert_many([_order("A-1"), _order("A-9", status="LOST", delivered=None)])
    db.statement_lines.insert_one(_line("ST-A-W35", "A-1", "2026-W35", 70_350))
    assert {r["order_code"] for r in reconcile_statement("ST-A-W35", db, now=NOW)} == {"A-1"}


# ── Chuyển định dạng và golden với labels.json ──
@needs_data
def test_converted_rules_are_valid_and_data_driven():
    ds = chat_v1.load_source()
    from core.rules import rules_from_documents

    rules = rules_from_documents(ds["carrier_rules"])
    a, b, c = rules["carrier_a"], rules["carrier_b"], rules["carrier_c"]
    assert a.return_flat_by_region == {"noi_tinh": 5_000} and not b.return_flat_by_region
    assert all(r.payout_basis == "period_end" for r in rules.values())
    assert a.insurance_fee(2_117_000) == 10_600 and c.insurance_fee(622_000) == 2_500
    assert b.policy_for("DEFECTIVE").collect_cod and not b.policy_for("LOST").charge_shipping
    assert {o["region"] for o in ds["orders"]} == {"noi_tinh", "noi_vung", "lien_vung"}


@needs_data
def test_carriers_with_merged_fees_drop_separate_columns():
    lines = chat_v1.load_source()["statement_lines"]
    by = {c: next(ln for ln in lines if ln["carrier"] == c) for c in ("carrier_a", "carrier_b", "carrier_c")}
    assert "insurance_fee" in by["carrier_a"] and "return_shipping_fee" in by["carrier_a"]
    assert "return_shipping_fee" in by["carrier_b"] and "insurance_fee" not in by["carrier_b"]
    assert "insurance_fee" not in by["carrier_c"] and "return_shipping_fee" not in by["carrier_c"]


def _last_weeks(ds: dict, weeks=("2026-W41", "2026-W42")) -> dict:
    """Bộ con gồm mọi đơn và bảng kê của vài tuần cuối (mongomock chậm; cả 8 tuần kiểm bằng
    `python -m generator.chat_v1 --check-only` và trên Atlas)."""
    sids = {ln["statement_id"] for ln in ds["statement_lines"] if ln["period"] in weeks}
    return {
        **ds,
        "statement_lines": [ln for ln in ds["statement_lines"] if ln["statement_id"] in sids],
        "labels": {**ds["labels"], "lines": [x for x in ds["labels"]["lines"] if x["statement_id"] in sids]},
        "manifest": {**ds["manifest"], "statements": sorted(sids)},
    }


@needs_data
def test_engine_reproduces_every_label_to_the_dong():
    ds = _last_weeks(chat_v1.load_source())
    db = mongomock.MongoClient()["chat_v1_golden"]
    chat_v1.load_to_db(ds, db, reset=True)
    now = datetime.fromisoformat(ds["labels"]["meta"]["now"])
    counts = chat_v1.reconcile_all(ds, db, now=now)
    result = chat_v1.verify(ds, db)
    assert result["ok"], result["mismatches"][:5]
    assert result["labels"] == len(ds["labels"]["lines"]) > 1_000
    assert sum(counts.values()) == len(ds["labels"]["lines"])
    incident = [x for x in ds["labels"]["lines"] if x["incident"]]
    assert incident and all(x["diff_type"] == "FEE_MISMATCH" and x["carrier"] == "carrier_c" for x in incident)


@needs_data
def test_converted_documents_fit_contract_schemas():
    import json

    ds = chat_v1.load_source()
    props = {
        name: set(json.loads((chat_v1.Path(__file__).resolve().parents[2] / "contracts" / "schemas" / f"{name}.json")
                             .read_text(encoding="utf-8"))["properties"])
        for name in ("orders", "statement_lines", "carrier_rules")
    }
    for name in ("orders", "statement_lines", "carrier_rules"):
        extra = set().union(*(set(d) for d in ds[name])) - props[name] - {"raw"}
        # display_name, transfer_fee_cod_only, status_policy: tên quen dùng trong core/rules.py, chưa nằm trong schema
        assert extra <= {"display_name", "transfer_fee_cod_only", "status_policy"}, (name, extra)
