"""[B] Aggregation Pipeline: Claim sắp hết hạn khiếu nại.

Chênh lệch doanh nghiệp nhận thiếu (diff > 0) còn hạn khiếu nại nhưng hết hạn trong `within_hours` giờ tới,
$lookup sang `claims` để biết đã có claim chưa. Chỉ giữ chênh lệch còn phải xử lý (chưa có claim,
hoặc claim còn ở DRAFT / APPROVED). $facet ra danh sách (gần hạn trước) và tóm tắt theo hãng.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from common.enums import Collections
from core.periods import to_db

COLLECTION = Collections.RECONCILIATIONS
OPEN_CLAIM_STATUSES = ["DRAFT", "APPROVED"]
CLOSED_CLAIM_STATUSES = ["SUBMITTED", "RECOVERED", "REJECTED"]


def pipeline(now: datetime, within_hours: float = 24, carrier: str | None = None, limit: int = 200) -> list[dict]:
    now_db = to_db(now)
    match: dict = {
        "claim_deadline_at": {"$gt": now_db, "$lte": to_db(now + timedelta(hours=within_hours))},
        "diff": {"$gt": 0},
        "diff_type": {"$ne": "NONE"},
    }
    if carrier:
        match["carrier"] = carrier
    return [
        {"$match": match},
        {"$lookup": {
            "from": Collections.CLAIMS,
            "localField": "reconciliation_id",
            "foreignField": "reconciliation_id",
            "pipeline": [{"$project": {"_id": 0, "claim_id": 1, "status": 1}}],
            "as": "claims",
        }},
        {"$match": {"claims.status": {"$nin": CLOSED_CLAIM_STATUSES}}},
        {"$set": {
            "hours_left": {"$round": [{"$divide": [{"$subtract": ["$claim_deadline_at", now_db]}, 3_600_000]}, 2]},
            "claim": {"$first": "$claims"},
        }},
        {"$project": {
            "_id": 0, "reconciliation_id": 1, "statement_id": 1, "order_code": 1, "carrier": 1, "diff_type": 1,
            "diff": 1, "claim_deadline_at": 1, "hours_left": 1,
            "claim_id": "$claim.claim_id", "claim_status": "$claim.status",
        }},
        {"$facet": {
            "items": [{"$sort": {"claim_deadline_at": 1, "diff": -1}}, {"$limit": limit}],
            "by_carrier": [
                {"$group": {"_id": "$carrier", "count": {"$sum": 1}, "amount": {"$sum": "$diff"},
                            "min_hours_left": {"$min": "$hours_left"},
                            "without_claim": {"$sum": {"$cond": [{"$eq": [{"$type": "$claim_id"}, "missing"]}, 1, 0]}}}},
                {"$project": {"_id": 0, "carrier": "$_id", "count": 1, "amount": 1, "min_hours_left": 1,
                              "without_claim": 1}},
                {"$sort": {"carrier": 1}},
            ],
        }},
    ]


def run(db, now: datetime | None = None, within_hours: float = 24, carrier: str | None = None,
        limit: int = 200) -> dict:
    now = now or datetime.now(timezone.utc)
    return next(db[COLLECTION].aggregate(pipeline(now, within_hours, carrier, limit)), None) or {
        "items": [], "by_carrier": []}
