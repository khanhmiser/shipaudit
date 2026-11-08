"""[B] reconcile_statement(statement_id, db): ghép dòng bảng kê với đơn, tính diff,
phân loại diff_type, tính claim_deadline_at, ghi `reconciliations`.

Idempotent theo (statement_id, order_code). Khớp contracts.interfaces.ReconcileFn.

Cách làm:
1. Đọc các dòng `statement_lines` của bảng kê, quy tắc mới nhất của hãng và các đơn liên quan.
2. Các đơn có hạn trả tiền thu hộ rơi vào kỳ của bảng kê mà không có dòng nào: MISSING_IN_STATEMENT.
3. Mỗi dòng: số tiền phải nhận = compute_expected (chỉ từ đơn và quy tắc), số tiền thực nhận = net_paid,
   chênh lệch = phải nhận − thực nhận. Phân loại theo thứ tự:
   COD_MISMATCH (tiền thu hộ ghi khác) → RETURN_FEE_DOUBLE (phí hoàn khác quy định) → FEE_MISMATCH (khoản
   trừ khác) → LATE_PAYOUT (tiền đúng nhưng đơn thuộc kỳ trước) → NONE.
   Hãng không có cột phí hoàn riêng (phí gộp) thì coi là RETURN_FEE_DOUBLE khi phần trừ dư đúng bằng phí hoàn.
4. Hạn khiếu nại = mốc + claim_window_hours của hãng. Mốc theo claim_deadline_anchor: lúc nhận bảng kê
   (ingested_at sớm nhất, mặc định) hoặc ngày giao của từng đơn.

Mỗi bản ghi có `reconciliation_id` = "<statement_id>:<order_code>" (claims dùng khóa này).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from pymongo import UpdateOne

from common.enums import Collections, DiffType
from contracts.interfaces import Breakdown
from core.engine import compute_expected, total_fees
from core.periods import as_aware, period_of, to_db
from core.rules import load_rule

FEE_FIELDS = (
    "shipping_fee", "insurance_fee", "return_shipping_fee", "storage_fee",
    "address_change_fee", "inspection_fee", "transfer_fee",
)
RETURN_LIKE_STATUSES = ("RETURNED", "RETURN_BY_CUSTOMER", "DEFECTIVE")
LINE_FIELDS = ("cod_collected", *FEE_FIELDS, "promotion", "net_paid")


def reconciliation_id(statement_id: str, order_code: str) -> str:
    return f"{statement_id}:{order_code}"


def classify(
    expected: Breakdown, line: dict | None, late: bool = False, return_fee_ref: int | None = None,
) -> DiffType:
    """`return_fee_ref`: phí hoàn hãng sẽ tính nếu áp dụng (kể cả khi quy tắc không cho tính, vd hàng lỗi).
    Chỉ cần với hãng gộp phí hoàn vào tổng cước; mặc định là phí hoàn đã tính trong `expected`."""
    if line is None:
        return DiffType.MISSING_IN_STATEMENT
    if "cod_collected" in line and line["cod_collected"] != expected.cod_collected:
        return DiffType.COD_MISMATCH
    if expected.expected_amount == line["net_paid"]:
        return DiffType.LATE_PAYOUT if late else DiffType.NONE
    if "return_shipping_fee" in line:
        if line["return_shipping_fee"] != expected.return_shipping_fee:
            return DiffType.RETURN_FEE_DOUBLE
    else:
        fee_excess = sum(line.get(f, 0) for f in FEE_FIELDS) - total_fees(expected)
        ref = expected.return_shipping_fee if return_fee_ref is None else return_fee_ref
        if ref > 0 and fee_excess == ref:
            return DiffType.RETURN_FEE_DOUBLE
    return DiffType.FEE_MISMATCH


def reconcile_statement(statement_id: str, db: Any, *, now: datetime | None = None) -> list[dict]:
    now = as_aware(now) if now else datetime.now(timezone.utc)
    lines = list(db[Collections.STATEMENT_LINES].find({"statement_id": statement_id}, {"_id": 0}))
    if not lines:
        return []
    carrier = lines[0]["carrier"]
    rule = load_rule(db, carrier)

    # Nạp trùng một file thì cùng order_code có nhiều dòng: giữ dòng cuối, ghi lại số dòng trùng.
    by_code: dict[str, dict] = {}
    dup = Counter(line["order_code"] for line in lines)
    for line in lines:
        by_code[line["order_code"]] = line
    orders = {
        o["order_code"]: o
        for o in db[Collections.ORDERS].find(
            {"order_code": {"$in": list(by_code)}, "carrier": carrier}, {"_id": 0}
        )
    }

    def due_period(order: dict) -> str:
        return rule.statement_period(as_aware(order["delivered_at"]))

    period = next((line["period"] for line in lines if line.get("period")), None)
    if period is None and orders:
        period = Counter(due_period(o) for o in orders.values()).most_common(1)[0][0]

    if period:
        start, end = rule.delivery_window(period)
        for o in db[Collections.ORDERS].find(
            {"carrier": carrier, "delivered_at": {"$gte": to_db(start), "$lt": to_db(end)}},
            {"_id": 0},
        ):
            orders.setdefault(o["order_code"], o)

    received = [as_aware(line["ingested_at"]) for line in lines if line.get("ingested_at")]
    received_at = min(received) if received else now

    def deadline_of(order: dict | None) -> datetime:
        delivered = as_aware(order["delivered_at"]) if order and order.get("delivered_at") else None
        return rule.claim_deadline_for(received_at, delivered)

    # Đơn chưa có dòng ở kỳ này nhưng đã nằm trong bảng kê kỳ sau: trả muộn, không phải thiếu.
    absent = [c for c in orders if c not in by_code]
    arrived_later = set()
    if period and absent:
        arrived_later = set(db[Collections.STATEMENT_LINES].distinct(
            "order_code", {"carrier": carrier, "order_code": {"$in": absent}, "period": {"$gt": period}}
        ))

    records = []
    late_codes = []
    for code in sorted(set(by_code) | set(orders)):
        line, order = by_code.get(code), orders.get(code)
        if line is None and order is not None and order["status"] == "LOST":
            continue  # thất lạc: bồi thường nằm ngoài công thức, không có dòng bảng kê là bình thường
        if line is None and code in arrived_later:
            continue
        deadline = deadline_of(order)
        rec: dict[str, Any] = {
            "reconciliation_id": reconciliation_id(statement_id, code),
            "statement_id": statement_id,
            "order_code": code,
            "carrier": carrier,
            "period": period,
            "rule_version": rule.version,
            "claim_deadline_at": to_db(deadline),
            "claim_hours_left": round((deadline - now).total_seconds() / 3600, 2),
            "updated_at": to_db(now),
        }
        if order is None:
            # Dòng bảng kê không khớp đơn nào của doanh nghiệp: giữ lại để người kiểm tra xem.
            actual = line["net_paid"]
            rec.update(expected_amount=0, actual_amount=actual, diff=-actual,
                       diff_type=DiffType.NONE.value, unmatched=True)
        else:
            expected = compute_expected(order, line, rule)
            late = line is not None and period is not None and due_period(order) < period
            if late:
                late_codes.append(code)
            actual = line["net_paid"] if line else 0
            # Đơn hoàn/trả/lỗi: phí hoàn hãng sẽ tính nếu áp dụng (hàng lỗi bị trừ phí hoàn là RETURN_FEE_DOUBLE).
            returned = order["status"] in RETURN_LIKE_STATUSES
            ref = rule.return_shipping_fee(expected.shipping_fee, order.get("region")) if returned else None
            rec.update(
                expected_amount=expected.expected_amount,
                actual_amount=actual,
                diff=expected.expected_amount - actual,
                diff_type=classify(expected, line, late, ref).value,
                breakdown=asdict(expected),
                order_status=order["status"],
                delivered_at=to_db(order["delivered_at"]),
                late=late,
            )
        if line is not None:
            rec["actual_breakdown"] = {f: line[f] for f in LINE_FIELDS if f in line}
            if dup[code] > 1:
                rec["duplicate_lines"] = dup[code]
        records.append(rec)

    db[Collections.RECONCILIATIONS].bulk_write(
        [
            UpdateOne(
                {"statement_id": statement_id, "order_code": r["order_code"]},
                {"$set": r, "$setOnInsert": {"created_at": to_db(now)}},
                upsert=True,
            )
            for r in records
        ],
        ordered=False,
    )
    _settle_missing(db, carrier, period, late_codes)
    return records


def _settle_missing(db: Any, carrier: str, period: str | None, late_codes: list[str]) -> None:
    """Bảng kê kỳ sau mang đơn về muộn: bản ghi MISSING_IN_STATEMENT cũ của đơn đó không còn đúng.

    Xóa nếu chưa có claim; đã có claim thì giữ lại (con người đang xử lý) và ghi chú đơn đã về muộn."""
    if not late_codes or not period:
        return
    stale = list(db[Collections.RECONCILIATIONS].find(
        {"carrier": carrier, "order_code": {"$in": late_codes}, "diff_type": DiffType.MISSING_IN_STATEMENT.value,
         "period": {"$lt": period}},
        {"_id": 0, "reconciliation_id": 1},
    ))
    if not stale:
        return
    ids = [r["reconciliation_id"] for r in stale]
    claimed = set(db[Collections.CLAIMS].distinct("reconciliation_id", {"reconciliation_id": {"$in": ids}}))
    free = [i for i in ids if i not in claimed]
    if free:
        db[Collections.RECONCILIATIONS].delete_many({"reconciliation_id": {"$in": free}})
    if claimed:
        db[Collections.RECONCILIATIONS].update_many(
            {"reconciliation_id": {"$in": sorted(claimed)}}, {"$set": {"arrived_late": True}}
        )
