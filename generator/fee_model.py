"""[B] Mô hình phí tham chiếu: từ (đơn, quy tắc hãng) ra từng khoản của công thức đối soát.

Dùng để SINH bảng kê "đúng" rồi mới chèn lỗi. core/engine.compute_expected sau này phải ra cùng kết quả
trên mọi đơn (labels.json lưu expected_amount để đối chiếu).
Tiền là số nguyên VNĐ.
"""
from __future__ import annotations

import math

from contracts.interfaces import Breakdown
from core.money import to_vnd
from generator.carriers.params import REGIONS, STATUS_POLICY


def rate_row(rule: dict, region: str) -> dict:
    for row in rule["rate_table"]:
        if row["region"] == region:
            return row
    raise KeyError(region)


def chargeable_g(order: dict, rule: dict) -> int:
    """Khối lượng tính cước (g) = max(cân thực, thể tích / hệ số)."""
    volume_cm3 = order["length_cm"] * order["width_cm"] * order["height_cm"]
    volumetric_g = math.ceil(volume_cm3 / rule["dim_weight_divisor"] * 1000)
    return max(order["weight_g"], volumetric_g)


def shipping_fee(order: dict, rule: dict, region: str | None = None, extra_steps: int = 0) -> int:
    row = rate_row(rule, region or order["region"])
    over = max(0, chargeable_g(order, rule) - row["base_g"])
    steps = math.ceil(over / row["step_g"]) + extra_steps
    return row["base_fee"] + steps * row["step_fee"]


def step_fee(order: dict, rule: dict) -> int:
    return rate_row(rule, order["region"])["step_fee"]


def next_region(region: str) -> str | None:
    i = REGIONS.index(region)
    return REGIONS[i + 1] if i + 1 < len(REGIONS) else None


def insurance_fee(order: dict, rule: dict) -> int:
    s = rule["surcharges"]
    if s["insurance_pct"] <= 0 or order["declared_value"] < s["insurance_min_declared"]:
        return 0
    return to_vnd(round(order["declared_value"] * s["insurance_pct"] / 100) * 100)


def return_fee(order: dict, rule: dict, ship: int) -> int:
    if not STATUS_POLICY[order["status"]]["return_fee"]:
        return 0
    s = rule["surcharges"]
    if order["region"] == "noi_tinh" and s["return_flat_noi_tinh"]:
        return s["return_flat_noi_tinh"]
    return to_vnd(round(ship * s["return_pct"] / 500) * 500)


def storage_fee(order: dict, rule: dict) -> int:
    s = rule["surcharges"]
    days = max(0, order.get("storage_days", 0) - s["storage_free_days"])
    return days * s["storage_per_day"]


def address_change_fee(order: dict, rule: dict) -> int:
    return rule["surcharges"]["address_change"] if order.get("address_changed") else 0


def inspection_fee(order: dict, rule: dict) -> int:
    return rule["surcharges"]["inspection"] if order.get("inspected") else 0


def cod_collected(order: dict) -> int:
    return order["cod_amount"] if STATUS_POLICY[order["status"]]["cod_collected"] else 0


def transfer_fee(cod: int, rule: dict) -> int:
    return rule["transfer_fee"] if cod > 0 else 0


def breakdown(order: dict, rule: dict) -> Breakdown:
    """Các khoản đúng quy định của MỘT đơn."""
    ship = shipping_fee(order, rule)
    cod = cod_collected(order)
    return Breakdown(
        cod_collected=cod,
        prepaid_by_shop=order.get("prepaid_by_shop", 0),
        shipping_fee=ship,
        insurance_fee=insurance_fee(order, rule),
        return_shipping_fee=return_fee(order, rule, ship),
        storage_fee=storage_fee(order, rule),
        address_change_fee=address_change_fee(order, rule),
        inspection_fee=inspection_fee(order, rule),
        transfer_fee=transfer_fee(cod, rule),
    )
