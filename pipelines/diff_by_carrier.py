"""[B] Aggregation Pipeline: Tổng chênh lệch theo hãng/kỳ ($group, $facet).

Một lượt đọc `reconciliations`, $facet ra 4 bảng: theo hãng, theo hãng × loại chênh lệch,
theo hãng × kỳ, và tổng. Đây là thước đo chung để so sánh các hãng (không xếp hạng hãng).
- `diff_amount`: tổng chênh lệch (phải nhận − thực nhận), chỉ tính bản ghi có chênh lệch.
- `owed_amount`: phần chênh lệch dương (doanh nghiệp nhận thiếu).
"""
from __future__ import annotations

from common.enums import Collections

COLLECTION = Collections.RECONCILIATIONS

_IS_DIFF = {"$ne": ["$diff_type", "NONE"]}


def _sums() -> dict:
    return {
        "records": {"$sum": 1},
        "diff_count": {"$sum": {"$cond": [_IS_DIFF, 1, 0]}},
        "diff_amount": {"$sum": {"$cond": [_IS_DIFF, "$diff", 0]}},
        "owed_amount": {"$sum": {"$cond": [{"$and": [_IS_DIFF, {"$gt": ["$diff", 0]}]}, "$diff", 0]}},
        "expected_amount": {"$sum": "$expected_amount"},
        "actual_amount": {"$sum": "$actual_amount"},
    }


def _flat(keys: list[str]) -> dict:
    return {"_id": 0, **{k: f"$_id.{k}" for k in keys}, **{k: 1 for k in _sums()}}


def pipeline(carrier: str | None = None, periods: list[str] | None = None) -> list[dict]:
    match: dict = {}
    if carrier:
        match["carrier"] = carrier
    if periods:
        match["period"] = {"$in": periods}
    return [
        {"$match": match},
        {"$facet": {
            "by_carrier": [
                {"$group": {"_id": {"carrier": "$carrier"}, **_sums()}},
                {"$project": _flat(["carrier"])},
                {"$sort": {"carrier": 1}},
            ],
            "by_type": [
                {"$match": {"diff_type": {"$ne": "NONE"}}},
                {"$group": {"_id": {"carrier": "$carrier", "diff_type": "$diff_type"},
                            "diff_count": {"$sum": 1}, "diff_amount": {"$sum": "$diff"}}},
                {"$project": {"_id": 0, "carrier": "$_id.carrier", "diff_type": "$_id.diff_type",
                              "diff_count": 1, "diff_amount": 1}},
                {"$sort": {"carrier": 1, "diff_type": 1}},
            ],
            "by_period": [
                {"$group": {"_id": {"carrier": "$carrier", "period": "$period"}, **_sums()}},
                {"$project": _flat(["carrier", "period"])},
                {"$sort": {"carrier": 1, "period": 1}},
            ],
            "totals": [
                {"$group": {"_id": None, **_sums()}},
                {"$project": {"_id": 0}},
            ],
        }},
    ]


def run(db, carrier: str | None = None, periods: list[str] | None = None) -> dict:
    out = next(db[COLLECTION].aggregate(pipeline(carrier, periods)), None) or {}
    out["totals"] = (out.get("totals") or [{}])[0]
    return out
