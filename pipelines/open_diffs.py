"""[B] Aggregation Pipeline: Chênh lệch còn phải xử lý, chia theo hãng × loại × mức hạn khiếu nại.

Nguồn cho job metric `shipaudit.biz.*` (core/metrics_job.py). Chỉ lấy khoản doanh nghiệp nhận thiếu (diff > 0)
chưa xử lý xong: chưa có claim, hoặc claim còn ở DRAFT / APPROVED (cùng cách hiểu với claims_expiring).
`deadline` chia theo giờ còn lại tới hạn khiếu nại, cùng mốc với "Mức khẩn" trên giao diện:
expired (đã quá hạn), lt24h, lt48h, lt96h, later. $facet ra tổng theo từng nhóm và giờ còn lại ngắn nhất của mỗi hãng.
"""
from __future__ import annotations

from datetime import datetime, timezone

from common.enums import Collections
from core.periods import to_db
from pipelines.claims_expiring import CLOSED_CLAIM_STATUSES

COLLECTION = Collections.RECONCILIATIONS
DEADLINE_BUCKETS = ("expired", "lt24h", "lt48h", "lt96h", "later")


def pipeline(now: datetime, carrier: str | None = None) -> list[dict]:
    now_db = to_db(now)
    match: dict = {"diff": {"$gt": 0}, "diff_type": {"$ne": "NONE"}}
    if carrier:
        match["carrier"] = carrier
    return [
        {"$match": match},
        {"$lookup": {
            "from": Collections.CLAIMS,
            "localField": "reconciliation_id",
            "foreignField": "reconciliation_id",
            "pipeline": [{"$project": {"_id": 0, "status": 1}}],
            "as": "claims",
        }},
        {"$match": {"claims.status": {"$nin": CLOSED_CLAIM_STATUSES}}},
        {"$set": {"hours_left": {"$divide": [{"$subtract": ["$claim_deadline_at", now_db]}, 3_600_000]}}},
        {"$set": {"deadline": {"$switch": {
            "branches": [
                {"case": {"$lte": ["$hours_left", 0]}, "then": "expired"},
                {"case": {"$lt": ["$hours_left", 24]}, "then": "lt24h"},
                {"case": {"$lt": ["$hours_left", 48]}, "then": "lt48h"},
                {"case": {"$lt": ["$hours_left", 96]}, "then": "lt96h"},
            ],
            "default": "later",
        }}}},
        {"$facet": {
            "buckets": [
                {"$group": {"_id": {"carrier": "$carrier", "diff_type": "$diff_type", "deadline": "$deadline"},
                            "count": {"$sum": 1}, "amount": {"$sum": "$diff"}}},
                {"$project": {"_id": 0, "carrier": "$_id.carrier", "diff_type": "$_id.diff_type",
                              "deadline": "$_id.deadline", "count": 1, "amount": 1}},
                {"$sort": {"carrier": 1, "diff_type": 1, "deadline": 1}},
            ],
            "nearest": [
                {"$match": {"hours_left": {"$gt": 0}}},
                {"$group": {"_id": "$carrier", "min_hours_left": {"$min": "$hours_left"}, "count": {"$sum": 1}}},
                {"$project": {"_id": 0, "carrier": "$_id", "min_hours_left": {"$round": ["$min_hours_left", 2]},
                              "count": 1}},
                {"$sort": {"carrier": 1}},
            ],
        }},
    ]


def run(db, now: datetime | None = None, carrier: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return next(db[COLLECTION].aggregate(pipeline(now, carrier)), None) or {"buckets": [], "nearest": []}
