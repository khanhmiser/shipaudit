"""[B] Aggregation Pipeline: Kết quả khiếu nại, theo hãng × trạng thái claim.

Cho giao diện (Tổng quan: đã khiếu nại, chờ hãng phản hồi, đã thu hồi) và job metric `shipaudit.biz.*`.
`amount` là tiền doanh nghiệp khiếu nại; `recovered` là tiền hãng đã hoàn lại (chỉ claim RECOVERED có `recovered_amount`).
"""
from __future__ import annotations

from common.enums import Collections

COLLECTION = Collections.CLAIMS


def pipeline(carrier: str | None = None) -> list[dict]:
    stages: list[dict] = []
    if carrier:
        stages.append({"$match": {"carrier": carrier}})
    stages += [
        {"$group": {"_id": {"carrier": "$carrier", "status": "$status"},
                    "count": {"$sum": 1},
                    "amount": {"$sum": "$amount"},
                    "recovered": {"$sum": {"$ifNull": ["$recovered_amount", 0]}}}},
        {"$project": {"_id": 0, "carrier": "$_id.carrier", "status": "$_id.status",
                      "count": 1, "amount": 1, "recovered": 1}},
        {"$sort": {"carrier": 1, "status": 1}},
    ]
    return stages


def run(db, carrier: str | None = None) -> list[dict]:
    return list(db[COLLECTION].aggregate(pipeline(carrier)))
