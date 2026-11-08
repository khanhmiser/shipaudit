"""[B] Hàm đọc cho Streamlit và job metric. ui/ chỉ đọc Mongo qua file này (không qua API của A)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from common.enums import Collections
from core.claims import OPEN_STATUSES, ClaimService
from core.rules import CarrierRule, load_rule
from pipelines import claims_expiring, claims_outcome, diff_by_carrier, diff_trend, missing_orders


def _clean(doc: dict | None) -> dict | None:
    if doc is not None:
        doc.pop("_id", None)
    return doc


def list_reconciliations(
    db: Any, carrier: str | None = None, period: str | None = None, diff_type: str | None = None,
    only_diff: bool = True, limit: int = 1_000,
) -> list[dict]:
    query: dict = {}
    if carrier:
        query["carrier"] = carrier
    if period:
        query["period"] = period
    if diff_type:
        query["diff_type"] = diff_type
    elif only_diff:
        query["diff_type"] = {"$ne": "NONE"}
    cur = db[Collections.RECONCILIATIONS].find(query, {"_id": 0}).sort([("diff", -1), ("order_code", 1)])
    return list(cur.limit(limit))


def get_reconciliation(db: Any, reconciliation_id: str) -> dict | None:
    return db[Collections.RECONCILIATIONS].find_one({"reconciliation_id": reconciliation_id}, {"_id": 0})


def order_detail(db: Any, order_code: str) -> dict:
    """Đơn, các dòng bảng kê gốc và mọi kết quả đối soát của đơn (bằng chứng cho claim)."""
    return {
        "order": db[Collections.ORDERS].find_one({"order_code": order_code}, {"_id": 0}),
        "lines": list(db[Collections.STATEMENT_LINES].find({"order_code": order_code}, {"_id": 0})),
        "reconciliations": list(db[Collections.RECONCILIATIONS].find({"order_code": order_code}, {"_id": 0})),
        "claims": [_clean(c) for c in db[Collections.CLAIMS].find({"order_code": order_code})],
    }


def carriers(db: Any) -> list[dict]:
    """Mã và tên hiển thị của các hãng, theo bản quy tắc mới nhất của mỗi hãng."""
    return list(db[Collections.CARRIER_RULES].aggregate([
        {"$sort": {"carrier": 1, "version": -1}},
        {"$group": {"_id": "$carrier", "display_name": {"$first": "$display_name"}}},
        {"$project": {"_id": 0, "carrier": "$_id", "display_name": 1}},
        {"$sort": {"carrier": 1}},
    ]))


def carrier_rule_documents(db: Any) -> list[dict]:
    """Bản quy tắc mới nhất của từng hãng, đúng như lưu trong carrier_rules (để giao diện hiển thị thông tin hãng)."""
    return list(db[Collections.CARRIER_RULES].aggregate([
        {"$sort": {"carrier": 1, "version": -1}},
        {"$group": {"_id": "$carrier", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$project": {"_id": 0}},
        {"$sort": {"carrier": 1}},
    ]))


def periods(db: Any) -> list[str]:
    return sorted(p for p in db[Collections.RECONCILIATIONS].distinct("period") if p)


def diff_summary(db: Any, carrier: str | None = None, period_list: list[str] | None = None) -> dict:
    return diff_by_carrier.run(db, carrier, period_list)


def diff_trend_by_day(db: Any, carrier: str | None = None, since: datetime | None = None,
                      until: datetime | None = None, unit: str = "day") -> list[dict]:
    """Chênh lệch theo ngày giao (`unit="week"`: theo tuần, bắt đầu thứ Hai), kèm cộng dồn và tổng 7 ngày."""
    return diff_trend.run(db, carrier, since, until, unit)


def missing_in_statement(db: Any, carrier: str, period: str) -> list[dict]:
    return missing_orders.run(db, carrier, period)


def expiring(db: Any, now: datetime | None = None, within_hours: float = 24, carrier: str | None = None) -> dict:
    return claims_expiring.run(db, now, within_hours, carrier)


def claim_outcomes(db: Any, carrier: str | None = None) -> list[dict]:
    """Số claim, tiền khiếu nại và tiền đã thu hồi theo hãng × trạng thái claim."""
    return claims_outcome.run(db, carrier)


def list_claims(db: Any, status: str | None = None, carrier: str | None = None) -> list[dict]:
    return ClaimService(db).list(status, carrier)


def claim_by_reconciliation(db: Any) -> dict[str, dict]:
    """{reconciliation_id: claim} cho mọi bản ghi đối soát đã có claim. Có nhiều claim thì ưu tiên claim đang mở,
    rồi đến claim mới nhất."""
    out: dict[str, dict] = {}
    for c in ClaimService(db).list(limit=5_000):  # mới nhất trước
        cur = out.get(c["reconciliation_id"])
        if cur is None or (c["status"] in OPEN_STATUSES and cur["status"] not in OPEN_STATUSES):
            out[c["reconciliation_id"]] = c
    return out


def carrier_rule(db: Any, carrier: str) -> CarrierRule | None:
    """Quy tắc mới nhất của hãng (để giải thích cách tính). Không có hoặc sai định dạng thì None."""
    try:
        return load_rule(db, carrier)
    except ValueError:
        return None
