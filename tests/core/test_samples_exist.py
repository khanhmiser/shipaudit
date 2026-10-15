"""Bảo đảm 3 file bảng kê mẫu và 6 schema có mặt (hợp đồng giữa A và B)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_samples_exist():
    for c in "abc":
        assert (ROOT / "contracts" / "samples" / f"statement_carrier_{c}.csv").exists()


def test_schemas_are_valid_json():
    names = ["carrier_rules", "orders", "statement_lines", "reconciliations", "claims", "ingest_events"]
    for n in names:
        data = json.loads((ROOT / "contracts" / "schemas" / f"{n}.json").read_text(encoding="utf-8"))
        assert data["type"] == "object" and "required" in data
