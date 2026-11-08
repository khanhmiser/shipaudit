"""Golden test cho core/engine.compute_expected: từng khoản tính tay, khớp từng đồng.

Tham số lấy từ generator/carriers/params.py (kịch bản giả định).
"""
from dataclasses import asdict

import pytest

from core.engine import compute_expected, total_fees
from core.rules import rules_from_documents
from generator.carriers.params import carrier_rule_documents

RULES = rules_from_documents(carrier_rule_documents())
DOCS = {d["carrier"]: d for d in carrier_rule_documents()}

# (mã ca, đơn, các khoản mong đợi khác 0, số tiền phải nhận)
GOLDEN = [
    (
        "A giao thành công, khối lượng quy đổi = 500 g",
        {"carrier": "carrier_a", "status": "DELIVERED", "region": "noi_tinh", "weight_g": 400,
         "length_cm": 20, "width_cm": 15, "height_cm": 10, "cod_amount": 350_000},
        {"cod_collected": 350_000, "shipping_fee": 22_000, "insurance_fee": 3_500, "transfer_fee": 1_650},
        322_850,
    ),
    (
        "A liên vùng, quy đổi 4 kg vượt mốc, đủ phụ phí và khuyến mãi",
        {"carrier": "carrier_a", "status": "DELIVERED", "region": "lien_vung", "weight_g": 1_200,
         "length_cm": 40, "width_cm": 30, "height_cm": 20, "cod_amount": 1_200_000,
         "storage_days": 5, "address_changes": 1, "inspection": True, "promotion": 5_000},
        {"cod_collected": 1_200_000, "promotion": 5_000, "shipping_fee": 62_000, "insurance_fee": 12_000,
         "storage_fee": 6_000, "address_change_fee": 10_000, "inspection_fee": 3_000, "transfer_fee": 1_650},
        1_110_350,
    ),
    (
        "A hoàn hàng: không thu hộ, phí hoàn 50%, không phí chuyển khoản",
        {"carrier": "carrier_a", "status": "RETURNED", "region": "noi_vung", "weight_g": 800,
         "cod_amount": 450_000, "storage_days": 4},
        {"shipping_fee": 32_000, "insurance_fee": 4_500, "storage_fee": 3_000, "return_shipping_fee": 16_000},
        -55_500,
    ),
    (
        "A hàng lỗi: miễn phí hoàn, giá trị dưới mức bảo hiểm",
        {"carrier": "carrier_a", "status": "DEFECTIVE", "region": "noi_tinh", "weight_g": 1_000,
         "cod_amount": 200_000},
        {"shipping_fee": 25_000},
        -25_000,
    ),
    (
        "A đơn trả trước (không thu hộ), bảo hiểm theo giá trị khai báo",
        {"carrier": "carrier_a", "status": "DELIVERED", "region": "noi_tinh", "weight_g": 300,
         "cod_amount": 0, "declared_value": 500_000},
        {"shipping_fee": 22_000, "insurance_fee": 5_000},
        -27_000,
    ),
    (
        "B trả hàng: thu hộ vẫn chuyển, phí hoàn 100%, doanh nghiệp đã nộp trước phí trả hàng",
        {"carrier": "carrier_b", "status": "RETURN_BY_CUSTOMER", "region": "noi_tinh", "weight_g": 2_500,
         "length_cm": 30, "width_cm": 20, "height_cm": 10, "cod_amount": 500_000,
         "return_fee_paid_by_shop": 30_000},
        {"cod_collected": 500_000, "return_fee_paid_by_shop": 30_000, "shipping_fee": 30_000,
         "return_shipping_fee": 30_000},
        470_000,
    ),
    (
        "B liên vùng 6,5 kg, bảo hiểm 0,5%, lưu kho trong hạn miễn phí, doanh nghiệp trả trước",
        {"carrier": "carrier_b", "status": "DELIVERED", "region": "lien_vung", "weight_g": 6_500,
         "cod_amount": 1_500_000, "storage_days": 2, "inspection": True, "prepaid_by_shop": 20_000},
        {"cod_collected": 1_500_000, "prepaid_by_shop": 20_000, "shipping_fee": 69_000, "insurance_fee": 7_500},
        1_443_500,
    ),
    (
        "B hàng lỗi: tính phí hoàn",
        {"carrier": "carrier_b", "status": "DEFECTIVE", "region": "noi_vung", "weight_g": 900,
         "cod_amount": 300_000},
        {"shipping_fee": 30_000, "return_shipping_fee": 30_000},
        -60_000,
    ),
    (
        "C nội vùng, bảo hiểm làm tròn half up, đổi địa chỉ, đồng kiểm",
        {"carrier": "carrier_c", "status": "DELIVERED", "region": "noi_vung", "weight_g": 1_700,
         "cod_amount": 612_345, "address_changes": 1, "inspection": True},
        {"cod_collected": 612_345, "shipping_fee": 34_000, "insurance_fee": 4_899, "address_change_fee": 12_000,
         "inspection_fee": 5_000, "transfer_fee": 1_100},
        555_346,
    ),
    (
        "C hoàn hàng: phí hoàn cố định, lưu kho vượt 5 ngày",
        {"carrier": "carrier_c", "status": "RETURNED", "region": "lien_vung", "weight_g": 300,
         "cod_amount": 0, "declared_value": 800_000, "storage_days": 7},
        {"shipping_fee": 29_000, "insurance_fee": 6_400, "return_shipping_fee": 15_000, "storage_fee": 4_000},
        -54_400,
    ),
    (
        "C hàng lỗi: tính phí hoàn cố định",
        {"carrier": "carrier_c", "status": "DEFECTIVE", "region": "noi_tinh", "weight_g": 500,
         "cod_amount": 100_000},
        {"shipping_fee": 20_000, "return_shipping_fee": 15_000},
        -35_000,
    ),
    (
        "C thất lạc: không khoản nào",
        {"carrier": "carrier_c", "status": "LOST", "region": "noi_tinh", "weight_g": 500,
         "cod_amount": 300_000, "inspection": True},
        {},
        0,
    ),
]


@pytest.mark.parametrize("name, order, items, expected", GOLDEN, ids=[g[0] for g in GOLDEN])
def test_golden(name, order, items, expected):
    b = compute_expected(order, None, RULES[order["carrier"]])
    got = {k: v for k, v in asdict(b).items() if v != 0}
    assert got == items
    assert b.expected_amount == expected


def test_rule_as_mongo_document_gives_same_result():
    _, order, _, expected = GOLDEN[1]
    assert compute_expected(order, None, DOCS["carrier_a"]).expected_amount == expected


def test_statement_line_does_not_change_expected():
    _, order, _, expected = GOLDEN[0]
    line = {"cod_collected": 1, "shipping_fee": 999_999, "net_paid": 0}
    assert compute_expected(order, line, RULES["carrier_a"]).expected_amount == expected


def test_wrong_carrier_rule_rejected():
    _, order, _, _ = GOLDEN[0]
    with pytest.raises(ValueError):
        compute_expected(order, None, RULES["carrier_b"])


def test_total_fees():
    _, order, items, _ = GOLDEN[1]
    b = compute_expected(order, None, RULES["carrier_a"])
    assert total_fees(b) == 62_000 + 12_000 + 6_000 + 10_000 + 3_000 + 1_650


def test_all_amounts_are_int():
    for _, order, _, _ in GOLDEN:
        b = compute_expected(order, None, RULES[order["carrier"]])
        assert all(type(v) is int for v in asdict(b).values())
