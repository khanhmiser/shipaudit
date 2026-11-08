"""[B] compute_expected(order, line, rule) -> Breakdown, đúng công thức đối soát.

Công thức nằm ở contracts.interfaces.Breakdown.expected_amount. File này chỉ điền từng khoản
theo quy tắc hãng (core/rules.py) và dữ kiện của đơn, không chứa con số nào của hãng.

Dữ kiện đơn được dùng (ngoài schema orders, các trường thêm đều tùy chọn, mặc định 0):
- `region`, `weight_g`, `length_cm`, `width_cm`, `height_cm`: phí giao hàng.
- `cod_amount`: tiền thu hộ. `declared_value` (mặc định = cod_amount): phí bảo hiểm.
- `status`: chọn status_policy của hãng (hoàn hàng, trả hàng, hàng lỗi, thất lạc).
- `storage_days`, `address_changes`, `inspection` (true/false): lưu kho, đổi địa chỉ, đồng kiểm.
- `prepaid_by_shop`: doanh nghiệp trả trước cho hãng (cộng lại).
- `return_fee_paid_by_shop`: phí trả hàng doanh nghiệp đã nộp trước, được cộng lại để bù phí chuyển hoàn.
- `promotion`: khuyến mãi của hãng.

Số tiền phải nhận chỉ tính từ đơn và quy tắc, không lấy từ bảng kê: `line` chỉ để giữ chữ ký
theo kế hoạch, không ảnh hưởng kết quả.
"""
from __future__ import annotations

from contracts.interfaces import Breakdown
from core.rules import CarrierRule


def _as_rule(rule: CarrierRule | dict) -> CarrierRule:
    return rule if isinstance(rule, CarrierRule) else CarrierRule.from_doc(rule)


def compute_expected(order: dict, line: dict | None, rule: CarrierRule | dict) -> Breakdown:
    rule = _as_rule(rule)
    if order.get("carrier") and order["carrier"] != rule.carrier:
        raise ValueError(f"đơn {order.get('order_code')} thuộc {order['carrier']}, quy tắc của {rule.carrier}")
    policy = rule.policy_for(order["status"])
    cod_amount = int(order.get("cod_amount") or 0)

    b = Breakdown(
        prepaid_by_shop=int(order.get("prepaid_by_shop") or 0),
        return_fee_paid_by_shop=int(order.get("return_fee_paid_by_shop") or 0),
        promotion=int(order.get("promotion") or 0),
    )
    if policy.collect_cod:
        b.cod_collected = cod_amount

    if policy.charge_shipping:
        weight = rule.chargeable_weight_g(
            int(order["weight_g"]),
            int(order.get("length_cm") or 0),
            int(order.get("width_cm") or 0),
            int(order.get("height_cm") or 0),
        )
        b.shipping_fee = rule.shipping_fee(order["region"], weight)
        declared = order.get("declared_value")
        b.insurance_fee = rule.insurance_fee(int(cod_amount if declared is None else declared))
        b.storage_fee = rule.storage_fee(int(order.get("storage_days") or 0))
        b.address_change_fee = rule.address_change_fee(int(order.get("address_changes") or 0))
        b.inspection_fee = rule.inspection_fee(1 if order.get("inspection") else 0)

    if policy.charge_return:
        b.return_shipping_fee = rule.return_shipping_fee(b.shipping_fee, order.get("region"))

    b.transfer_fee = rule.transfer_fee(b.cod_collected)
    return b


def total_fees(b: Breakdown) -> int:
    """Tổng các khoản trừ."""
    return (
        b.shipping_fee + b.insurance_fee + b.return_shipping_fee + b.storage_fee
        + b.address_change_fee + b.inspection_fee + b.transfer_fee
    )
