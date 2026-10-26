"""[B] Aggregation Pipeline: Xu hướng chênh lệch theo thời gian ($setWindowFields).

Gom chênh lệch theo hãng × ngày giao (giờ Việt Nam), rồi $setWindowFields theo từng hãng:
- `cumulative_amount`, `cumulative_count`: cộng dồn từ đầu.
- `amount_7d`, `count_7d`: cửa sổ 7 ngày gần nhất (tính theo ngày, kể cả ngày trống).
Chỉ dùng tổng, không dùng trung bình, để tiền luôn là số nguyên.
"""
from __future__ import annotations

from datetime import datetime

from common.enums import Collections
from core.periods import to_db

COLLECTION = Collections.RECONCILIATIONS
TZ = "+07:00"


def pipeline(carrier: str | None = None, since: datetime | None = None, until: datetime | None = None) -> list[dict]:
    match: dict = {"diff_type": {"$ne": "NONE"}, "delivered_at": {"$type": "date"}}
    if since or until:
        rng = {"$type": "date"}
        if since:
            rng["$gte"] = to_db(since)
        if until:
            rng["$lt"] = to_db(until)
        match["delivered_at"] = rng
    if carrier:
        match["carrier"] = carrier
    return [
        {"$match": match},
        {"$group": {
            "_id": {"carrier": "$carrier",
                    "day": {"$dateTrunc": {"date": "$delivered_at", "unit": "day", "timezone": TZ}}},
            "diff_count": {"$sum": 1},
            "diff_amount": {"$sum": "$diff"},
        }},
        {"$project": {"_id": 0, "carrier": "$_id.carrier", "day": "$_id.day", "diff_count": 1, "diff_amount": 1}},
        {"$setWindowFields": {
            "partitionBy": "$carrier",
            "sortBy": {"day": 1},
            "output": {
                "cumulative_amount": {"$sum": "$diff_amount", "window": {"documents": ["unbounded", "current"]}},
                "cumulative_count": {"$sum": "$diff_count", "window": {"documents": ["unbounded", "current"]}},
                "amount_7d": {"$sum": "$diff_amount", "window": {"range": [-6, 0], "unit": "day"}},
                "count_7d": {"$sum": "$diff_count", "window": {"range": [-6, 0], "unit": "day"}},
            },
        }},
        {"$sort": {"carrier": 1, "day": 1}},
    ]


def run(db, carrier: str | None = None, since: datetime | None = None, until: datetime | None = None) -> list[dict]:
    return list(db[COLLECTION].aggregate(pipeline(carrier, since, until)))
