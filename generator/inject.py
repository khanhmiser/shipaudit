"""[B] Cài 5 loại chênh lệch (FEE_MISMATCH, RETURN_FEE_DOUBLE, MISSING_IN_STATEMENT, COD_MISMATCH,
LATE_PAYOUT) cùng ca hoàn/trả/hàng lỗi. Xuất labels.json làm đáp án đối chiếu.

Mỗi đơn cài nhiều nhất một loại. Tỉ lệ là xác suất khi đơn đủ điều kiện (giả định của kịch bản);
Carrier B có hệ số cao hơn cho kịch bản "bảng kê Carrier B bị trừ lệch nhiều".
Với mỗi chênh lệch, label ghi các bản ghi đối soát phải phát hiện được (statement_id, diff_type, diff).
"""
from __future__ import annotations

import random
from dataclasses import replace

from common.enums import DiffType
from core.engine import compute_expected
from core.periods import as_aware, period_of, shift_period
from core.rules import CarrierRule
from generator.statements import statement_id_for

RATES = {
    DiffType.RETURN_FEE_DOUBLE: 0.15,    # trong số đơn có phí hoàn
    DiffType.FEE_MISMATCH: 0.03,
    DiffType.COD_MISMATCH: 0.015,
    DiffType.MISSING_IN_STATEMENT: 0.01,
    DiffType.LATE_PAYOUT: 0.01,
}
CARRIER_FACTOR = {"carrier_a": 1.0, "carrier_b": 2.0, "carrier_c": 1.0}
FEE_DELTAS = (2_000, 2_500, 3_000, 5_000, 7_000, 10_000, 15_000)
COD_PCTS = (5, 10, 20)


def _eligible(t: DiffType, expected, order, due_period: str, last_period: str) -> bool:
    if t is DiffType.RETURN_FEE_DOUBLE:
        return expected.return_shipping_fee > 0
    if t is DiffType.FEE_MISMATCH:
        return expected.shipping_fee > 0
    if t is DiffType.COD_MISMATCH:
        return expected.cod_collected >= 20_000
    if t is DiffType.MISSING_IN_STATEMENT:
        return order["status"] == "DELIVERED" and expected.expected_amount > 0
    if t is DiffType.LATE_PAYOUT:
        return due_period != last_period and expected.expected_amount > 0
    return False


def inject(
    orders: list[dict], rules: dict[str, CarrierRule], periods: list[str], rng: random.Random,
    rates: dict[DiffType, float] = RATES, carrier_factor: dict[str, float] = CARRIER_FACTOR,
) -> tuple[list[dict], list[dict]]:
    """Trả về (placements, anomalies).

    placements: [{order, expected, actual, period}], `actual` là các khoản hãng ghi trên bảng kê,
    `period` là kỳ bảng kê chứa đơn (None nếu bị bỏ sót).
    """
    placements, anomalies = [], []
    for order in orders:
        rule = rules[order["carrier"]]
        expected = compute_expected(order, None, rule)
        due_period = period_of(rule.payout_due(as_aware(order["delivered_at"])))
        actual, period = replace(expected), due_period
        sid = statement_id_for(order["carrier"], due_period)

        r, acc, chosen = rng.random(), 0.0, None
        factor = carrier_factor.get(order["carrier"], 1.0)
        for t, p in rates.items():
            if _eligible(t, expected, order, due_period, periods[-1]):
                acc += p * factor
                if r < acc:
                    chosen = t
                    break

        detections = []
        if chosen is DiffType.FEE_MISMATCH:
            delta = rng.choice([d for d in FEE_DELTAS if d != expected.return_shipping_fee])
            actual.shipping_fee += delta
            detections = [(sid, chosen, delta)]
        elif chosen is DiffType.COD_MISMATCH:
            delta = max(1_000, expected.cod_collected * rng.choice(COD_PCTS) // 100 // 1_000 * 1_000)
            actual.cod_collected -= delta
            detections = [(sid, chosen, delta)]
        elif chosen is DiffType.RETURN_FEE_DOUBLE:
            actual.return_shipping_fee *= 2
            detections = [(sid, chosen, expected.return_shipping_fee)]
        elif chosen is DiffType.MISSING_IN_STATEMENT:
            period = None
            detections = [(sid, chosen, expected.expected_amount)]
        elif chosen is DiffType.LATE_PAYOUT:
            period = shift_period(due_period, 1)
            # Đơn về ở bảng kê kỳ sau: chỉ bản ghi LATE_PAYOUT ở kỳ sau. Kỳ trước không báo thiếu
            # vì tiền đã về (xem core.reconcile: đơn có ở kỳ sau thì không phải MISSING_IN_STATEMENT).
            detections = [(statement_id_for(order["carrier"], period), chosen, 0)]

        placements.append({"order": order, "expected": expected, "actual": actual, "period": period})
        if chosen:
            anomalies.append({
                "order_code": order["order_code"],
                "carrier": order["carrier"],
                "status": order["status"],
                "injected": chosen.value,
                "detections": [
                    {"statement_id": s, "diff_type": t.value, "diff": d} for s, t, d in detections
                ],
            })
    return placements, anomalies
