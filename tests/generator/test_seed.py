"""Kiểm tra bộ sinh dữ liệu: đúng lược đồ contracts/, nhất quán số tiền, tái lập được."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest

from contracts.interfaces import Breakdown  # noqa: F401  (đảm bảo contracts import được)
from generator import fee_model, seed
from generator.carriers.params import CARRIER_PARAMS

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts" / "schemas"
NOW = datetime.fromisoformat(seed.DEFAULT_NOW)


@pytest.fixture(scope="module")
def built():
    return seed.generate(seed=42, now=NOW, weeks=8, incident=True)


def _plain(doc: dict) -> dict:
    """Đổi datetime thành chuỗi ISO để kiểm tra bằng JSON Schema."""
    out = {}
    for k, v in doc.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, dict):
            out[k] = _plain(v)
        else:
            out[k] = v
    return out


def _validate(collection: str, docs: list[dict]) -> None:
    schema = json.loads((SCHEMAS / f"{collection}.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for d in docs:
        errors = list(validator.iter_errors(_plain(d)))
        assert not errors, (collection, d.get("order_code") or d.get("carrier"), errors[0].message)


def test_docs_match_contract_schemas(built):
    _validate("orders", built["orders"])
    _validate("carrier_rules", built["rules"])
    _validate("statement_lines", built["lines"])
    _validate("ingest_events", built["events"])


def test_unique_keys(built):
    codes = [o["order_code"] for o in built["orders"]]
    assert len(codes) == len(set(codes))
    keys = [(ln["statement_id"], ln["order_code"]) for ln in built["lines"]]
    assert len(keys) == len(set(keys))
    label_keys = [(lb["statement_id"], lb["order_code"]) for lb in built["labels"]]
    assert len(label_keys) == len(set(label_keys))


def test_expected_amount_recomputed_from_orders(built):
    orders = {o["order_code"]: o for o in built["orders"]}
    for lb in built["labels"]:
        o = orders[lb["order_code"]]
        rule = CARRIER_PARAMS[o["carrier"]]
        assert fee_model.breakdown(o, rule).expected_amount == lb["expected_amount"], lb["order_code"]


def test_clean_lines_pay_exactly_expected(built):
    for lb in built["labels"]:
        if lb["diff_type"] == "NONE":
            assert lb["actual_amount"] == lb["expected_amount"] and lb["diff"] == 0
        if lb["diff_type"] == "LATE_PAYOUT":
            assert lb["diff"] == 0
        if lb["diff_type"] == "MISSING_IN_STATEMENT":
            assert lb["actual_amount"] == 0 and lb["diff"] == lb["expected_amount"]
        if lb["diff_type"] in ("FEE_MISMATCH", "RETURN_FEE_DOUBLE", "COD_MISMATCH"):
            assert lb["diff"] > 0, lb  # hãng trả thiếu


def test_missing_lines_absent_and_others_present(built):
    present = {(ln["statement_id"], ln["order_code"]) for ln in built["lines"]}
    for lb in built["labels"]:
        key = (lb["statement_id"], lb["order_code"])
        assert (key in present) == lb["present_in_statement"]


def test_late_lines_appear_in_later_period(built):
    for lb in built["labels"]:
        if lb["diff_type"] == "LATE_PAYOUT":
            assert lb["statement_id"].split("W")[-1] > lb["delivery_period"].split("W")[-1]


def test_lost_orders_have_no_line(built):
    lost = {o["order_code"] for o in built["orders"] if o["status"] == "LOST"}
    assert lost == {e["order_code"] for e in built["excluded"]}
    assert not lost & {ln["order_code"] for ln in built["lines"]}


def test_raw_csv_matches_sample_headers_and_arithmetic(built):
    orders = {o["order_code"]: o for o in built["orders"]}
    labels = {(lb["statement_id"], lb["order_code"]): lb for lb in built["labels"]}
    sample_dir = ROOT / "contracts" / "samples"
    n_rows = Counter()
    for name, text in built["raw_files"].items():
        carrier = name.split("_")[1] + "_" + name.split("_")[2]
        sample = (sample_dir / f"statement_{carrier}.csv").read_text(encoding="utf-8").splitlines()[0]
        lines = text.strip().splitlines()
        assert lines[0] == sample, name
        delim = ";" if carrier == "carrier_b" else ","
        sid = None
        for row in csv.reader(lines[1:], delimiter=delim):
            code = row[0]
            o = orders[code]
            n_rows[carrier] += 1
            lb = next(v for (s, c), v in labels.items() if c == code)
            prepaid = 0 if lb["subtype"] == "PREPAID_NOT_CREDITED" else o["prepaid_by_shop"]
            if carrier == "carrier_a":
                cod, ship, ins, ret, xfer, net = map(int, row[1:])
                assert net == cod + prepaid - (ship + ins + ret + xfer), code
            elif carrier == "carrier_b":
                cod, ship, ret, stor, net = map(int, row[1:])
                assert net == cod + prepaid - (ship + ret + stor), code
            else:
                cod, total, note, net = int(row[1]), int(row[2]), row[3], int(row[4])
                addr = 5000 if "doi dia chi" in note else 0
                assert net == cod + prepaid - (total + addr), code
    assert sum(n_rows.values()) == len(built["lines"])


def test_timing_paid_before_received(built):
    for ln in built["lines"]:
        assert ln["paid_at"] < ln["ingested_at"]


def test_claim_clock_demo_windows(built):
    """Kỳ mới nhất: C còn ít giờ nhất (24h - 6h), A (72h - 20h), B (168h - 40h)."""
    last = {}
    for ln in built["lines"]:
        last[ln["carrier"]] = max(last.get(ln["carrier"], ln["ingested_at"]), ln["ingested_at"])
    for carrier, hours_ago in {"carrier_c": 6, "carrier_a": 20, "carrier_b": 40}.items():
        left = CARRIER_PARAMS[carrier]["claim_window_hours"] - (NOW - last[carrier]).total_seconds() / 3600
        assert left == CARRIER_PARAMS[carrier]["claim_window_hours"] - hours_ago


def test_incident_only_carrier_c_latest_period(built):
    inc = [lb for lb in built["labels"] if lb["incident"]]
    assert inc and all(lb["carrier"] == "carrier_c" and lb["statement_id"].endswith("W42") for lb in inc)
    base_c = [lb for lb in built["labels"] if lb["carrier"] == "carrier_c" and lb["statement_id"].endswith("W41")]
    cur_c = [lb for lb in built["labels"] if lb["carrier"] == "carrier_c" and lb["statement_id"].endswith("W42")]
    rate = lambda xs: sum(1 for x in xs if x["diff_type"] == "FEE_MISMATCH") / len(xs)  # noqa: E731
    assert rate(cur_c) > 3 * rate(base_c)


def test_all_five_diff_types_present(built):
    types = {lb["diff_type"] for lb in built["labels"]}
    assert types >= {"FEE_MISMATCH", "RETURN_FEE_DOUBLE", "MISSING_IN_STATEMENT", "COD_MISMATCH", "LATE_PAYOUT", "NONE"}


def test_deterministic():
    a = seed.generate(seed=7, now=NOW, weeks=3, incident=True)
    b = seed.generate(seed=7, now=NOW, weeks=3, incident=True)
    assert a["raw_files"] == b["raw_files"]
    assert [ln["net_paid"] for ln in a["lines"]] == [ln["net_paid"] for ln in b["lines"]]
    c = seed.generate(seed=8, now=NOW, weeks=3, incident=True)
    assert a["raw_files"] != c["raw_files"]


def test_money_is_int(built):
    for ln in built["lines"]:
        for k in ("cod_collected", "shipping_fee", "net_paid", "transfer_fee"):
            assert isinstance(ln[k], int)
    for o in built["orders"]:
        for k in ("cod_amount", "prepaid_by_shop", "declared_value", "weight_g"):
            assert isinstance(o[k], int)
