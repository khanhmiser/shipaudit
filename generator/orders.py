"""[B] Từ "đơn nền" (synthetic hoặc Olist) dựng đơn hoàn chỉnh theo contracts/schemas/orders.json.

Gán hãng, mã đơn, trạng thái (hoàn hàng, trả hàng, hàng lỗi, thất lạc), thu hộ, phụ phí phát sinh
và ngày giao. Mọi xác suất là giả định của kịch bản demo. Cùng seed thì ra cùng kết quả.
"""
from __future__ import annotations

import random
from datetime import timedelta

from core.periods import period_bounds, to_iso
from core.rules import CarrierRule

CARRIER_SHARE = (("carrier_a", 40), ("carrier_b", 35), ("carrier_c", 25))
STATUS_SHARE = (
    ("DELIVERED", 86), ("RETURNED", 7), ("RETURN_BY_CUSTOMER", 4), ("DEFECTIVE", 2), ("LOST", 1),
)
COD_SHARE = 0.85            # tỉ lệ đơn có thu hộ
PREPAID_SHARE = 0.04        # doanh nghiệp trả trước cho hãng
PROMOTION_SHARE = 0.05      # hãng khuyến mãi
ADDRESS_CHANGE_SHARE = 0.04
INSPECTION_SHARE = 0.12     # đồng kiểm
STORAGE_SHARE = 0.03        # đơn giao thành công nhưng có lưu kho
RETURN_FEE_PREPAID_SHARE = 0.30  # trong số đơn trả hàng


def _pick(rng: random.Random, table) -> str:
    names, weights = zip(*table)
    return rng.choices(names, weights)[0]


def _money(rng: random.Random, low: int, high: int, step: int = 1_000) -> int:
    return rng.randint(low // step, high // step) * step


def build_orders(base: list[dict], rng: random.Random, rules: dict[str, CarrierRule], periods: list[str]) -> list[dict]:
    window_start = period_bounds(periods[0])[0]
    window_seconds = int((period_bounds(periods[-1])[1] - window_start).total_seconds())
    counters = {c: 0 for c, _ in CARRIER_SHARE}
    orders = []
    for b in base:
        carrier = _pick(rng, CARRIER_SHARE)
        counters[carrier] += 1
        rule = rules[carrier]
        status = b.get("status_hint") or _pick(rng, STATUS_SHARE)
        goods_value = b["goods_value"]
        is_return = status in ("RETURNED", "RETURN_BY_CUSTOMER", "DEFECTIVE")

        # Hạn trả tiền thu hộ rải đều trong các kỳ; ngày giao = hạn − T+n của hãng.
        due_at = window_start + timedelta(minutes=rng.randrange(window_seconds // 60))
        delivered_at = due_at - timedelta(days=rule.cod_payout_days)

        order = {
            "order_code": f"{carrier[-1].upper()}-{counters[carrier]:06d}",
            "carrier": carrier,
            "region": b["region"],
            "weight_g": b["weight_g"],
            "length_cm": b["length_cm"],
            "width_cm": b["width_cm"],
            "height_cm": b["height_cm"],
            "cod_amount": goods_value if rng.random() < COD_SHARE else 0,
            "declared_value": goods_value,
            "prepaid_by_shop": _money(rng, 10_000, 30_000) if rng.random() < PREPAID_SHARE else 0,
            "return_fee_paid_by_shop": 0,
            "promotion": _money(rng, 2_000, 10_000) if rng.random() < PROMOTION_SHARE else 0,
            "storage_days": 0,
            "address_changes": 1 if rng.random() < ADDRESS_CHANGE_SHARE else 0,
            "inspection": rng.random() < INSPECTION_SHARE,
            "status": status,
            "delivered_at": to_iso(delivered_at),
            "source": b["source"],
        }
        if is_return:
            order["storage_days"] = rng.randint(0, 8)
        elif rng.random() < STORAGE_SHARE:
            order["storage_days"] = rng.randint(1, 6)
        if status == "RETURN_BY_CUSTOMER" and rng.random() < RETURN_FEE_PREPAID_SHARE:
            order["return_fee_paid_by_shop"] = _money(rng, 10_000, 20_000)
        if b.get("source_ref"):
            order["source_ref"] = b["source_ref"]
        orders.append(order)
    return orders
