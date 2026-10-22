"""[B] Chèn 5 loại chênh lệch (FEE_MISMATCH, RETURN_FEE_DOUBLE, MISSING_IN_STATEMENT, COD_MISMATCH,
LATE_PAYOUT) vào bảng kê, cùng ca hoàn/trả/hàng lỗi. Mỗi dòng có nhãn đáp án (labels.json).

Mỗi đơn có đúng một nhãn. Tỷ lệ chèn là giả định của đội, KHÔNG phản ánh tỷ lệ thị trường.
Kịch bản sự cố nghiệp vụ (incident): kỳ mới nhất của Carrier C đổi cách tính cước, một phần đơn
liên tỉnh/nội miền bị tính thêm một bậc khối lượng -> tỷ lệ FEE_MISMATCH vọt lên so với nền.
"""
from __future__ import annotations

import dataclasses
import random

from core.money import to_vnd
from generator import fee_model
from generator.carriers.params import CARRIER_PARAMS, STATUS_POLICY

# Xác suất nền theo dòng đủ điều kiện.
P_FEE = 0.020
P_MISSING = 0.010
P_COD = 0.011
P_LATE = 0.010
P_RETURN_FEE = 0.15  # trên các dòng hoàn/trả/hàng lỗi
P_INCIDENT = 0.50  # trên đơn nội miền/liên miền của Carrier C ở kỳ mới nhất

INCIDENT_CARRIER = "carrier_c"
DIFF_ORDER = ("COD_MISMATCH", "FEE_MISMATCH", "LATE_PAYOUT", "MISSING_IN_STATEMENT", "RETURN_FEE_DOUBLE")


def _forced_return_fee(order: dict, rule: dict, ship: int) -> int:
    """Phí hoàn nếu hãng tính cho đơn không thuộc diện hoàn (dùng cho CHARGED_ON_DEFECTIVE)."""
    s = rule["surcharges"]
    if order["region"] == "noi_tinh" and s["return_flat_noi_tinh"]:
        return s["return_flat_noi_tinh"]
    return to_vnd(round(ship * s["return_pct"] / 500) * 500)


def plan_line(rng: random.Random, order: dict, last_week: int, incident: bool) -> dict | None:
    """Trả về mô tả một dòng bảng kê (hoặc None nếu đơn không có dòng, ví dụ thất lạc)."""
    rule = CARRIER_PARAMS[order["carrier"]]
    status = order["status"]
    if status == "LOST":
        return None

    bd = fee_model.breakdown(order, rule)
    expected = bd.expected_amount
    comp = {
        "cod": bd.cod_collected,
        "ship": bd.shipping_fee,
        "ins": bd.insurance_fee,
        "ret": bd.return_shipping_fee,
        "stor": bd.storage_fee,
        "addr": bd.address_change_fee,
        "insp": bd.inspection_fee,
        "xfer": bd.transfer_fee,
        "prepaid_credit": bd.prepaid_by_shop,
    }
    week = order["_week"]
    plan = {
        "order_code": order["order_code"],
        "carrier": order["carrier"],
        "delivery_week": week,
        "appear_week": week,
        "present": True,
        "diff_type": "NONE",
        "subtype": None,
        "incident": False,
        "expected": expected,
        "breakdown": dataclasses.asdict(bd),
        "comp": comp,
    }

    # Kịch bản sự cố: ưu tiên, không chồng thêm loại khác lên cùng đơn.
    if (
        incident
        and order["carrier"] == INCIDENT_CARRIER
        and week == last_week
        and order["region"] != "noi_tinh"
        and rng.random() < P_INCIDENT
    ):
        comp["ship"] += fee_model.step_fee(order, rule)
        plan.update(diff_type="FEE_MISMATCH", subtype="C_STEP_CHANGE", incident=True)
        return _finish(plan)

    probs: list[tuple[str, float]] = []
    for kind in DIFF_ORDER:
        if kind == "MISSING_IN_STATEMENT" and status in ("DELIVERED", "RETURN_BY_CUSTOMER", "DEFECTIVE"):
            probs.append((kind, P_MISSING))
        elif kind == "COD_MISMATCH" and comp["cod"] > 0:
            probs.append((kind, P_COD))
        elif kind == "LATE_PAYOUT" and week < last_week:
            probs.append((kind, P_LATE))
        elif kind == "FEE_MISMATCH":
            probs.append((kind, P_FEE))
        elif kind == "RETURN_FEE_DOUBLE" and status in ("RETURNED", "RETURN_BY_CUSTOMER", "DEFECTIVE"):
            probs.append((kind, P_RETURN_FEE))

    r = rng.random()
    acc = 0.0
    chosen = None
    for kind, p in probs:
        acc += p
        if r < acc:
            chosen = kind
            break
    if chosen is None:
        return _finish(plan)

    plan["diff_type"] = chosen
    if chosen == "FEE_MISMATCH":
        options = ["WEIGHT_TIER_UP"]
        if fee_model.next_region(order["region"]):
            options.append("REGION_UPGRADE")
        if comp["prepaid_credit"] > 0:
            options.append("PREPAID_NOT_CREDITED")
        if rule["surcharges"]["insurance_pct"] > 0 and comp["ins"] == 0:
            options.append("UNEXPECTED_INSURANCE")
        sub = rng.choice(options)
        plan["subtype"] = sub
        if sub == "WEIGHT_TIER_UP":
            comp["ship"] += fee_model.step_fee(order, rule)
        elif sub == "REGION_UPGRADE":
            comp["ship"] = fee_model.shipping_fee(order, rule, region=fee_model.next_region(order["region"]))
        elif sub == "PREPAID_NOT_CREDITED":
            comp["prepaid_credit"] = 0
        else:
            comp["ins"] = max(1000, to_vnd(round(order["declared_value"] * rule["surcharges"]["insurance_pct"] / 100) * 100))
    elif chosen == "RETURN_FEE_DOUBLE":
        if status == "DEFECTIVE":
            plan["subtype"] = "CHARGED_ON_DEFECTIVE"
            comp["ret"] = _forced_return_fee(order, rule, comp["ship"])
        else:
            plan["subtype"] = "DOUBLE_CHARGED"
            comp["ret"] = comp["ret"] * 2
        if comp["ret"] == bd.return_shipping_fee:  # không tạo được chênh lệch thì bỏ
            plan.update(diff_type="NONE", subtype=None)
    elif chosen == "MISSING_IN_STATEMENT":
        plan["subtype"] = "ABSENT_ROW"
        plan["present"] = False
    elif chosen == "COD_MISMATCH":
        plan["subtype"] = "SHORT_COLLECTED"
        cod = comp["cod"]
        delta = max(10_000, round(cod * rng.uniform(0.05, 0.35) / 1000) * 1000)
        comp["cod"] = cod - min(delta, cod - 1000)
    elif chosen == "LATE_PAYOUT":
        plan["subtype"] = "CARRY_OVER"
        plan["appear_week"] = week + 1
    return _finish(plan)


def _finish(plan: dict) -> dict:
    comp = plan["comp"]
    if not plan["present"]:
        net = 0
    else:
        net = (
            comp["cod"]
            + comp["prepaid_credit"]
            - (comp["ship"] + comp["ins"] + comp["ret"] + comp["stor"] + comp["addr"] + comp["insp"] + comp["xfer"])
        )
    plan["net_paid"] = net
    plan["diff"] = plan["expected"] - net
    return plan
