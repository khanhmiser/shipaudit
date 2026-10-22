"""[B] Tham số Carrier A/B/C (GIẢ ĐỊNH của đội, đổ vào collection carrier_rules).

Ba hãng là hãng giả lập, không phải GHN/GHTK. Cấu trúc tham số tham khảo chính sách công khai:
- Phí chuyển hoàn: nội tỉnh 5.000đ, tuyến khác 50% cước chiều đi (kiểu GHN) -> Carrier A.
- Phí bảo hiểm theo giá khai (kiểu GHN "phí khai giá") -> Carrier A, C.
- Phí chuyển khoản tiền thu hộ cố định (kiểu GHN/GHTK) -> Carrier A.
Mức cước, hệ số khối lượng quy đổi, lịch trả COD, hạn khiếu nại là số do đội đặt, KHÔNG phản ánh thị trường.

Cột bảng kê thô của từng hãng khớp contracts/samples/*.csv.
"""
from __future__ import annotations

REGIONS = ("noi_tinh", "noi_mien", "lien_mien")

# Bảng tra theo trạng thái: khoản nào được tính.
# ĐỀ XUẤT, đang chờ chốt (status_policy). Sửa tại đây là sinh lại toàn bộ dữ liệu.
STATUS_POLICY: dict[str, dict] = {
    "DELIVERED": {"cod_collected": True, "return_fee": False},
    "RETURNED": {"cod_collected": False, "return_fee": True},  # hoàn hàng (giao thất bại)
    "RETURN_BY_CUSTOMER": {"cod_collected": True, "return_fee": True},  # trả hàng sau khi nhận
    "DEFECTIVE": {"cod_collected": True, "return_fee": False},  # hàng lỗi: chỉ cước giao, không phí hoàn
    "LOST": {"cod_collected": False, "return_fee": False},  # không có dòng trong bảng kê
}

CARRIER_PARAMS: dict[str, dict] = {
    # Kiểu GHN: nhiều cột phí tách riêng, phí chuyển khoản mỗi dòng thu hộ.
    "carrier_a": {
        "prefix": "A",
        "version": 1,
        "dim_weight_divisor": 6000,
        "rate_table": [
            {"region": "noi_tinh", "base_g": 500, "base_fee": 22000, "step_g": 500, "step_fee": 3000},
            {"region": "noi_mien", "base_g": 500, "base_fee": 28000, "step_g": 500, "step_fee": 4500},
            {"region": "lien_mien", "base_g": 500, "base_fee": 33000, "step_g": 500, "step_fee": 5500},
        ],
        "surcharges": {
            "insurance_pct": 0.005,
            "insurance_min_declared": 1_000_000,
            "return_flat_noi_tinh": 5000,
            "return_pct": 0.5,
            "storage_per_day": 0,
            "storage_free_days": 0,
            "address_change": 0,
            "inspection": 0,
        },
        "cod_payout_days": 2,
        "claim_window_hours": 72,
        "transfer_fee": 1650,
    },
    # Kiểu cột tiếng Việt, có phí lưu kho, không bảo hiểm, không phí chuyển khoản.
    "carrier_b": {
        "prefix": "B",
        "version": 1,
        "dim_weight_divisor": 5000,
        "rate_table": [
            {"region": "noi_tinh", "base_g": 1000, "base_fee": 26000, "step_g": 500, "step_fee": 3500},
            {"region": "noi_mien", "base_g": 1000, "base_fee": 31000, "step_g": 500, "step_fee": 5000},
            {"region": "lien_mien", "base_g": 1000, "base_fee": 36000, "step_g": 500, "step_fee": 6000},
        ],
        "surcharges": {
            "insurance_pct": 0.0,
            "insurance_min_declared": 0,
            "return_flat_noi_tinh": 0,
            "return_pct": 1.0,
            "storage_per_day": 3000,
            "storage_free_days": 2,
            "address_change": 0,
            "inspection": 0,
        },
        "cod_payout_days": 3,
        "claim_window_hours": 168,
        "transfer_fee": 0,
    },
    # Kiểu tổng phí gộp một cột; đổi địa chỉ trừ ngoài cột tổng (ghi chú "doi dia chi").
    "carrier_c": {
        "prefix": "C",
        "version": 1,
        "dim_weight_divisor": 4000,
        "rate_table": [
            {"region": "noi_tinh", "base_g": 500, "base_fee": 24000, "step_g": 500, "step_fee": 4000},
            {"region": "noi_mien", "base_g": 500, "base_fee": 29000, "step_g": 500, "step_fee": 5000},
            {"region": "lien_mien", "base_g": 500, "base_fee": 35000, "step_g": 500, "step_fee": 6500},
        ],
        "surcharges": {
            "insurance_pct": 0.004,
            "insurance_min_declared": 500_000,
            "return_flat_noi_tinh": 0,
            "return_pct": 0.5,
            "storage_per_day": 0,
            "storage_free_days": 0,
            "address_change": 5000,
            "inspection": 0,
        },
        "cod_payout_days": 1,
        "claim_window_hours": 24,
        "transfer_fee": 0,
    },
}

# Tỷ trọng đơn mỗi tuần và hệ số cho từng hãng (giả định).
CARRIER_WEEKLY_ORDERS = {"carrier_a": 250, "carrier_b": 210, "carrier_c": 190}
