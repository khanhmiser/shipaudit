"""[B] Aggregation Pipeline: Đối chiếu bảng kê với đơn, tìm đơn thiếu ($lookup).

Đơn của một hãng thuộc bảng kê kỳ P (theo carrier_rules.payout_basis: hạn trả tiền delivered_at + cod_payout_days
rơi vào tuần P, hoặc giao trong tuần P khi bảng kê theo kỳ giao hàng), $lookup sang `statement_lines` theo order_code. Đơn không có dòng nào trong bảng kê kỳ P là đơn thiếu.
Nếu đơn có mặt ở bảng kê kỳ khác thì `late = true` (chuyển chậm), không thì chưa từng được trả.
Số ngày T+n lấy từ carrier_rules, không hard-code.
"""
from __future__ import annotations

from common.enums import Collections
from core.periods import to_db
from core.rules import DEFAULT_PAYOUT_BASIS, delivery_window, load_rule

COLLECTION = Collections.ORDERS


def pipeline(carrier: str, period: str, cod_payout_days: int, payout_basis: str = DEFAULT_PAYOUT_BASIS) -> list[dict]:
    start, end = delivery_window(period, cod_payout_days, payout_basis)
    return [
        {"$match": {"carrier": carrier, "delivered_at": {"$gte": to_db(start), "$lt": to_db(end)}}},
        {"$lookup": {
            "from": Collections.STATEMENT_LINES,
            "localField": "order_code",
            "foreignField": "order_code",
            "pipeline": [
                {"$match": {"carrier": carrier}},
                {"$project": {"_id": 0, "statement_id": 1, "period": 1}},
            ],
            "as": "lines",
        }},
        {"$set": {
            "in_period": {"$filter": {"input": "$lines", "cond": {"$eq": ["$$this.period", period]}}},
            "other": {"$filter": {"input": "$lines", "cond": {"$ne": ["$$this.period", period]}}},
        }},
        {"$match": {"in_period": {"$size": 0}}},
        {"$project": {
            "_id": 0, "order_code": 1, "carrier": 1, "status": 1, "cod_amount": 1, "delivered_at": 1,
            "period": {"$literal": period},
            "other_statements": "$other.statement_id",
            "late": {"$gt": [{"$size": "$other"}, 0]},
        }},
        {"$sort": {"order_code": 1}},
    ]


def run(db, carrier: str, period: str) -> list[dict]:
    rule = load_rule(db, carrier)
    return list(db[COLLECTION].aggregate(pipeline(carrier, period, rule.cod_payout_days, rule.payout_basis)))
