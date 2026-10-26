"""Kiểm tra tham số Carrier A/B/C và core/rules.py (đọc quy tắc từ dữ liệu)."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.rules import CarrierRule, RuleError, load_rule, load_rules, rules_from_documents, upsert_rules
from generator.carriers.params import CARRIER_PARAMS, carrier_rule_documents

ROOT = Path(__file__).resolve().parents[2]
REGIONS = {"noi_tinh", "noi_vung", "lien_vung"}


class FakeCollection:
    """Đủ dùng cho find / replace_one, không cần Mongo thật."""

    def __init__(self):
        self.docs: list[dict] = []

    def find(self, query=None, projection=None):
        query = query or {}
        return [copy.deepcopy(d) for d in self.docs if all(d.get(k) == v for k, v in query.items())]

    def replace_one(self, flt, doc, upsert=False):
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in flt.items()):
                self.docs[i] = copy.deepcopy(doc)
                return
        if upsert:
            self.docs.append(copy.deepcopy(doc))


class FakeDB(dict):
    def __missing__(self, name):
        self[name] = FakeCollection()
        return self[name]


@pytest.fixture
def rules():
    return rules_from_documents(carrier_rule_documents())


# ── Tham số đầy đủ, khớp schema ──
def test_documents_have_schema_required_fields():
    schema = json.loads((ROOT / "contracts" / "schemas" / "carrier_rules.json").read_text(encoding="utf-8"))
    for doc in carrier_rule_documents():
        for field in schema["required"]:
            assert field in doc, (doc["carrier"], field)
        assert isinstance(doc["rate_table"], list)
        assert isinstance(doc["surcharges"], dict)
        assert isinstance(doc["transfer_fee"], int)


def test_three_carriers_three_regions(rules):
    assert set(rules) == {"carrier_a", "carrier_b", "carrier_c"}
    for r in rules.values():
        assert set(r.rates) == REGIONS


def test_claim_windows_differ_and_one_is_24h(rules):
    windows = [r.claim_window_hours for r in rules.values()]
    assert len(set(windows)) == 3
    assert 24 in windows


def test_no_float_anywhere_in_params():
    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        else:
            assert not isinstance(x, float), x

    walk(CARRIER_PARAMS)


# ── Khối lượng quy đổi và cước ──
def test_dim_weight_uses_carrier_divisor(rules):
    # 30 × 20 × 10 cm = 6000 cm3
    assert rules["carrier_a"].dim_weight_g(30, 20, 10) == 1_000  # /6000
    assert rules["carrier_b"].dim_weight_g(30, 20, 10) == 1_200  # /5000


def test_dim_weight_rounds_up(rules):
    assert rules["carrier_a"].dim_weight_g(10, 10, 10) == 167  # 166,67 g


def test_chargeable_weight_is_max(rules):
    a = rules["carrier_a"]
    assert a.chargeable_weight_g(400, 30, 20, 10) == 1_000
    assert a.chargeable_weight_g(2_500, 30, 20, 10) == 2_500
    assert a.chargeable_weight_g(800) == 800


@pytest.mark.parametrize(
    "weight_g, fee",
    [(1, 22_000), (500, 22_000), (501, 25_000), (1_000, 25_000), (2_000, 30_000), (3_000, 35_000),
     (3_001, 37_500), (3_500, 37_500), (4_200, 42_500)],
)
def test_carrier_a_noi_tinh_brackets(rules, weight_g, fee):
    assert rules["carrier_a"].shipping_fee("noi_tinh", weight_g) == fee


def test_carrier_b_extra_steps_of_1kg(rules):
    b = rules["carrier_b"]
    assert b.shipping_fee("lien_vung", 5_000) == 55_000
    assert b.shipping_fee("lien_vung", 5_001) == 62_000
    assert b.shipping_fee("lien_vung", 7_000) == 69_000


def test_fee_grows_with_distance(rules):
    for r in rules.values():
        for w in (300, 1_500, 6_000):
            assert r.shipping_fee("noi_tinh", w) < r.shipping_fee("noi_vung", w) < r.shipping_fee("lien_vung", w)


def test_unknown_region_raises(rules):
    with pytest.raises(RuleError):
        rules["carrier_a"].shipping_fee("mars", 500)


# ── Phụ phí ──
def test_insurance_threshold_and_rate(rules):
    a = rules["carrier_a"]
    assert a.insurance_fee(180_000) == 0
    assert a.insurance_fee(300_000) == 3_000
    assert a.insurance_fee(350_000) == 3_500
    assert rules["carrier_b"].insurance_fee(999_999) == 0
    assert rules["carrier_b"].insurance_fee(1_000_000) == 5_000
    assert rules["carrier_c"].insurance_fee(612_345) == 4_899  # 4898,76 làm tròn half up


def test_return_fee(rules):
    assert rules["carrier_a"].return_shipping_fee(33_000) == 16_500  # 50%
    assert rules["carrier_b"].return_shipping_fee(33_000) == 33_000  # 100%
    assert rules["carrier_c"].return_shipping_fee(33_000) == 15_000  # cố định


def test_storage_fee_after_free_days(rules):
    a = rules["carrier_a"]
    assert a.storage_fee(0) == 0
    assert a.storage_fee(3) == 0
    assert a.storage_fee(5) == 6_000
    assert rules["carrier_b"].storage_fee(5) == 12_000


def test_fixed_fees(rules):
    assert rules["carrier_a"].address_change_fee() == 10_000
    assert rules["carrier_c"].address_change_fee(2) == 24_000
    assert rules["carrier_b"].inspection_fee() == 0
    assert rules["carrier_c"].inspection_fee() == 5_000


def test_transfer_fee_only_for_cod_orders(rules):
    a = rules["carrier_a"]
    assert a.transfer_fee(350_000) == 1_650
    assert a.transfer_fee(0) == 0
    assert rules["carrier_b"].transfer_fee(350_000) == 0


# ── Hạn ──
def test_deadlines(rules):
    t = datetime(2026, 10, 22, 9, 0, tzinfo=timezone(timedelta(hours=7)))
    c = rules["carrier_c"]
    assert c.claim_deadline(t) == t + timedelta(hours=24)
    assert c.claim_hours_left(t, t + timedelta(hours=20)) == 4
    assert c.claim_hours_left(t, t + timedelta(hours=30)) == -6
    assert rules["carrier_b"].payout_due(t) == t + timedelta(days=3)


def test_claim_deadline_anchor_default_and_delivered():
    t_recv = datetime(2026, 10, 19, 9, 0, tzinfo=timezone(timedelta(hours=7)))
    t_deliv = t_recv - timedelta(days=5)
    docs = carrier_rule_documents()
    assert {d["claim_deadline_anchor"] for d in docs} == {"statement_received_at"}   # hãng giả lập
    b = CarrierRule.from_doc(next(d for d in docs if d["carrier"] == "carrier_b"))
    assert b.claim_deadline_for(t_recv, t_deliv) == t_recv + timedelta(hours=72)
    doc = copy.deepcopy(next(d for d in docs if d["carrier"] == "carrier_b"))
    doc["claim_deadline_anchor"] = "delivered_at"
    doc["claim_window_hours"] = 30 * 24          # 1 tháng kể từ ngày phát
    by_delivery = CarrierRule.from_doc(doc)
    assert by_delivery.claim_deadline_for(t_recv, t_deliv) == t_deliv + timedelta(days=30)
    assert by_delivery.claim_deadline_for(t_recv, None) == t_recv + timedelta(days=30)   # thiếu ngày giao
    doc.pop("claim_deadline_anchor")
    assert CarrierRule.from_doc(doc).claim_deadline_anchor == "statement_received_at"      # dữ liệu cũ


# ── Quy tắc là dữ liệu ──
def test_changing_data_changes_result_without_code_change():
    doc = next(d for d in carrier_rule_documents() if d["carrier"] == "carrier_a")
    before = CarrierRule.from_doc(doc)
    doc2 = copy.deepcopy(doc)
    doc2["dim_weight_divisor"] = 4_000
    doc2["rate_table"][0]["brackets"][0]["fee"] = 19_000
    doc2["claim_window_hours"] = 48
    after = CarrierRule.from_doc(doc2)
    assert before.dim_weight_g(30, 20, 10) == 1_000 and after.dim_weight_g(30, 20, 10) == 1_500
    assert before.shipping_fee("noi_tinh", 400) == 22_000 and after.shipping_fee("noi_tinh", 400) == 19_000
    assert after.claim_window_hours == 48


def test_newest_version_wins():
    docs = carrier_rule_documents()
    newer = copy.deepcopy(next(d for d in docs if d["carrier"] == "carrier_b"))
    newer["version"] = 2
    newer["claim_window_hours"] = 96
    assert rules_from_documents(docs + [newer])["carrier_b"].claim_window_hours == 96
    assert rules_from_documents([newer] + docs)["carrier_b"].claim_window_hours == 96


def test_upsert_is_idempotent_and_load_reads_back():
    db = FakeDB()
    upsert_rules(db, carrier_rule_documents())
    upsert_rules(db, carrier_rule_documents())
    assert len(db["carrier_rules"].docs) == 3
    assert set(load_rules(db)) == {"carrier_a", "carrier_b", "carrier_c"}
    assert load_rule(db, "carrier_c").claim_window_hours == 24
    with pytest.raises(RuleError):
        load_rule(db, "carrier_x")


# ── Dữ liệu sai bị chặn ──
@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("claim_window_hours"),
        lambda d: d.__setitem__("dim_weight_divisor", 6000.0),
        lambda d: d.__setitem__("dim_weight_divisor", 0),
        lambda d: d["rate_table"][0]["brackets"].reverse(),
        lambda d: d["rate_table"][0].__setitem__("brackets", []),
        lambda d: d["rate_table"].append(copy.deepcopy(d["rate_table"][0])),
        lambda d: d["surcharges"]["insurance"].__setitem__("rate_bp", 0.5),
        lambda d: d["rate_table"][1].__setitem__("extra_step_g", 0),
        lambda d: d.__setitem__("claim_deadline_anchor", "payment_date"),
    ],
    ids=["missing_field", "float_divisor", "zero_divisor", "unsorted_brackets", "empty_brackets",
         "duplicate_region", "float_rate", "zero_step", "unknown_anchor"],
)
def test_invalid_documents_rejected(mutate):
    doc = copy.deepcopy(carrier_rule_documents()[0])
    mutate(doc)
    with pytest.raises(RuleError):
        CarrierRule.from_doc(doc)


def test_invalid_document_not_written():
    db = FakeDB()
    bad = copy.deepcopy(carrier_rule_documents()[0])
    bad["dim_weight_divisor"] = 0
    with pytest.raises(RuleError):
        upsert_rules(db, [bad])
    assert db["carrier_rules"].docs == []


# ── Chính sách theo trạng thái (hoàn hàng, trả hàng, hàng lỗi) ──
def test_every_carrier_has_policy_for_every_status(rules):
    from common.enums import OrderStatus

    for r in rules.values():
        for s in OrderStatus:
            r.policy_for(s)


def test_policy_values(rules):
    assert rules["carrier_a"].policy_for("RETURNED").charge_return is True
    assert rules["carrier_a"].policy_for("RETURNED").collect_cod is False
    assert rules["carrier_a"].policy_for("RETURN_BY_CUSTOMER").collect_cod is True
    assert rules["carrier_a"].policy_for("DEFECTIVE").charge_return is False
    assert rules["carrier_b"].policy_for("DEFECTIVE").charge_return is True
    assert rules["carrier_c"].policy_for("LOST").charge_shipping is False


def test_bad_policy_rejected():
    doc = copy.deepcopy(carrier_rule_documents()[0])
    doc["status_policy"]["DELIVERED"]["collect_cod"] = "yes"
    with pytest.raises(RuleError):
        CarrierRule.from_doc(doc)
    doc = copy.deepcopy(carrier_rule_documents()[0])
    doc["status_policy"]["SHIPPING"] = doc["status_policy"]["DELIVERED"]
    with pytest.raises(RuleError):
        CarrierRule.from_doc(doc)
