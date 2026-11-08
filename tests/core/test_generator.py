"""Kiểm tra generator (B1, B5): chạy lại ra cùng dữ liệu, đúng schema, bảng kê đúng định dạng,
và đối soát trên dữ liệu seed phát hiện đủ, đúng loại, đúng số tiền mọi chênh lệch trong labels.json.
"""
import csv
import io
import json
from collections import Counter
from pathlib import Path

import mongomock
import pytest

from contracts.interfaces import Breakdown
from generator import olist_loader
from generator.seed import build_dataset, load_to_db, periods_before, reconcile_all, write_outputs
from generator.statements import FORMATS, normalize_row, render_row

ROOT = Path(__file__).resolve().parents[2]
N = 2_500


@pytest.fixture(scope="module")
def ds():
    return build_dataset("synthetic", seed=7, n=N)


@pytest.fixture(scope="module")
def reconciled(ds):
    db = mongomock.MongoClient().db
    load_to_db(ds, db)
    return db, reconcile_all(ds, db)


def test_same_seed_same_files(tmp_path):
    a = write_outputs(build_dataset("synthetic", seed=7, n=400), tmp_path / "a")
    b = write_outputs(build_dataset("synthetic", seed=7, n=400), tmp_path / "b")
    c = write_outputs(build_dataset("synthetic", seed=8, n=400), tmp_path / "c")
    assert a == b
    assert a != c
    assert (tmp_path / "a" / "labels.json").exists()
    assert len(list((tmp_path / "a" / "statements").glob("*.csv"))) == 9


def test_periods_before():
    assert periods_before("2026-10-20", 3) == ["2026-W40", "2026-W41", "2026-W42"]


def test_orders_match_schema(ds):
    schema = json.loads((ROOT / "contracts" / "schemas" / "orders.json").read_text(encoding="utf-8"))
    statuses = set(schema["properties"]["status"]["enum"])
    for o in ds["orders"]:
        for f in schema["required"]:
            assert f in o
        assert o["status"] in statuses
        assert all(type(o[k]) is int for k in ("weight_g", "cod_amount", "declared_value", "prepaid_by_shop"))
    assert len({o["order_code"] for o in ds["orders"]}) == N


def test_all_statuses_and_carriers_present(ds):
    m = ds["manifest"]["counts"]
    assert set(m["by_status"]) == {"DELIVERED", "RETURNED", "RETURN_BY_CUSTOMER", "DEFECTIVE", "LOST"}
    assert set(m["by_carrier"]) == {"carrier_a", "carrier_b", "carrier_c"}


def test_all_five_diff_types_injected(ds):
    assert set(ds["labels"]["summary"]) == {
        "FEE_MISMATCH", "RETURN_FEE_DOUBLE", "MISSING_IN_STATEMENT", "COD_MISMATCH", "LATE_PAYOUT",
    }


def test_statement_files_match_contract_headers(ds):
    for name, text in ds["statement_files"].items():
        carrier = {"A": "carrier_a", "B": "carrier_b", "C": "carrier_c"}[name.split("-")[1]]
        sample = (ROOT / "contracts" / "samples" / f"statement_{carrier}.csv").read_text(encoding="utf-8")
        assert text.splitlines()[0] == sample.splitlines()[0]
        rows = list(csv.DictReader(io.StringIO(text), delimiter=FORMATS[carrier]["delimiter"]))
        assert rows, name


def test_statement_lines_match_schema(ds):
    schema = json.loads((ROOT / "contracts" / "schemas" / "statement_lines.json").read_text(encoding="utf-8"))
    for ln in ds["statement_lines"]:
        for f in schema["required"]:
            assert f in ln
        assert set(ln) - {"raw"} <= set(schema["properties"])


def test_net_is_formula_over_actual_items():
    order = {"order_code": "A-1", "status": "DELIVERED"}
    actual = Breakdown(cod_collected=500_000, promotion=3_000, shipping_fee=30_000, insurance_fee=5_000,
                       storage_fee=6_000, address_change_fee=10_000, inspection_fee=3_000, transfer_fee=1_650)
    row = render_row("carrier_a", order, actual)
    assert row["ship_fee"] == "49000"  # giao + lưu kho + đổi địa chỉ + đồng kiểm
    assert int(row["net_paid"]) == actual.expected_amount
    ln = normalize_row("carrier_b", render_row("carrier_b", {**order, "order_code": "B-1"}, actual))
    assert ln["shipping_fee"] == 30_000 + 5_000 + 10_000 + 3_000 + 1_650 and ln["storage_fee"] == 6_000
    ln = normalize_row("carrier_c", render_row("carrier_c", {**order, "order_code": "C-1"}, actual))
    assert ln["shipping_fee"] == 55_650 and "insurance_fee" not in ln


def test_reconcile_finds_every_label_and_nothing_else(ds, reconciled):
    db, _ = reconciled
    found = {(r["statement_id"], r["order_code"]): r for r in db.reconciliations.find({}, {"_id": 0})}

    expected = {}
    for a in ds["labels"]["anomalies"]:
        for d in a["detections"]:
            expected[(d["statement_id"], a["order_code"])] = d
    misses = [
        (k, d, found.get(k, {}).get("diff_type"), found.get(k, {}).get("diff"))
        for k, d in expected.items()
        if k not in found or found[k]["diff_type"] != d["diff_type"] or found[k]["diff"] != d["diff"]
    ]
    assert not misses, misses[:5]

    extra = [k for k, r in found.items() if k not in expected and (r["diff_type"] != "NONE" or r["diff"] != 0)]
    assert not extra, extra[:5]
    assert not any(r.get("unmatched") for r in found.values())
    assert len(found) == len(ds["statement_lines"]) + sum(
        1 for d in expected.values() if d["diff_type"] == "MISSING_IN_STATEMENT"
    )


def test_reconcile_counts_by_type(ds, reconciled):
    _, counts = reconciled
    wanted = Counter(d["diff_type"] for a in ds["labels"]["anomalies"] for d in a["detections"])
    assert {k: v for k, v in counts.items() if k != "NONE"} == dict(wanted)


# ── Nguồn Olist: thử trên vài dòng CSV giả cùng định dạng ──
def _write_csv(path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


@pytest.fixture
def olist_dir(tmp_path):
    _write_csv(tmp_path / "olist_orders_dataset.csv", ["order_id", "customer_id", "order_status"],
               [["o1", "c1", "delivered"], ["o2", "c2", "canceled"], ["o3", "c3", "delivered"]])
    _write_csv(tmp_path / "olist_order_items_dataset.csv", ["order_id", "product_id", "seller_id", "price"],
               [["o1", "p1", "s1", "100.50"], ["o1", "p2", "s1", "20.00"], ["o2", "p1", "s2", "59.90"],
                ["o3", "p2", "s2", "10.00"]])
    _write_csv(tmp_path / "olist_products_dataset.csv",
               ["product_id", "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"],
               [["p1", "800", "30", "10", "20"], ["p2", "", "", "", ""]])
    _write_csv(tmp_path / "olist_customers_dataset.csv", ["customer_id", "customer_state"],
               [["c1", "SP"], ["c2", "RJ"], ["c3", "AM"]])
    _write_csv(tmp_path / "olist_sellers_dataset.csv", ["seller_id", "seller_state"], [["s1", "SP"], ["s2", "SP"]])
    return tmp_path


def test_olist_base_orders(olist_dir):
    import random

    base = {b["source_ref"]: b for b in olist_loader.base_orders(random.Random(1), 10, olist_dir)}
    assert set(base) == {"o1", "o2", "o3"}
    assert base["o1"]["region"] == "noi_tinh" and base["o2"]["region"] == "noi_vung"
    assert base["o3"]["region"] == "lien_vung"
    assert base["o1"]["goods_value"] == 566_000  # 120,50 BRL × 4.700 = 566.350, làm tròn nghìn
    assert base["o1"]["weight_g"] == 800 and (base["o1"]["length_cm"], base["o1"]["width_cm"]) == (30, 20)
    assert base["o2"]["status_hint"] == "RETURNED" and base["o1"]["status_hint"] is None
    assert base["o3"]["weight_g"] == 50  # thiếu khối lượng → mức tối thiểu


def test_olist_dataset_same_shape_as_synthetic(olist_dir):
    ds = build_dataset("olist", seed=1, n=10, olist_dir=olist_dir)
    assert {o["source"] for o in ds["orders"]} == {"olist"}
    synth = build_dataset("synthetic", seed=1, n=10)
    assert set(ds["orders"][0]) - {"source_ref"} == set(synth["orders"][0])


def test_olist_missing_files_message(tmp_path):
    import random

    with pytest.raises(FileNotFoundError, match="synthetic"):
        olist_loader.base_orders(random.Random(1), 10, tmp_path)
