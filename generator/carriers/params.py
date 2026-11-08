"""[B] Tham số Carrier A/B/C (giả định, đổ vào collection carrier_rules).

Đây là DỮ LIỆU của kịch bản giả định, không phải biểu phí của hãng thật nào.
Đổi tham số ở đây (hoặc sửa thẳng document trong Mongo, tăng `version`) thì engine
đổi theo, không phải sửa code. Đọc và kiểm tra bằng core/rules.py.

Quy ước:
- Tiền là số nguyên VNĐ. Tỉ lệ ghi bằng basis point (`*_bp`, 1 bp = 0,01%, 10000 bp = 100%)
  để không dùng float.
- Vùng giao (`region` của đơn): `noi_tinh`, `noi_vung`, `lien_vung`.
- `rate_table`: mỗi vùng một bảng mốc khối lượng (gram, tính theo khối lượng tính cước =
  max(khối lượng thật, khối lượng quy đổi)). Vượt mốc cuối thì cộng `extra_fee` cho mỗi
  `extra_step_g` (phần lẻ làm tròn lên một bước).
- Khối lượng quy đổi (kg) = dài × rộng × cao (cm) / `dim_weight_divisor`.
- `surcharges`:
  - `insurance`: `rate_bp` × giá trị khai báo, chỉ tính khi giá trị khai báo ≥ `min_declared_value`.
  - `return`: phí chuyển hoàn = `fixed` + `rate_bp` × phí giao hàng.
  - `storage`: `per_day` cho mỗi ngày lưu kho vượt `free_days`.
  - `address_change`, `inspection`: phí cố định mỗi lần.
- `transfer_fee`: phí chuyển khoản mỗi đơn; nếu `transfer_fee_cod_only` thì chỉ tính khi đơn có thu hộ.
- `cod_payout_days`: lịch trả tiền thu hộ T+n (ngày, tính từ lúc giao thành công; hoặc từ cuối kỳ giao khi payout_basis = period_end).
- `claim_window_hours`: hạn khiếu nại (giờ). Ba hãng ba mức, Carrier C chỉ 24 giờ.
- `claim_deadline_anchor`: mốc tính hạn khiếu nại, `statement_received_at` (lúc nhận bảng kê) hoặc `delivered_at`
  (ngày giao, như Luật Bưu chính 2010, Điều 38: 1 tháng kể từ ngày phát với khiếu nại về cước). Ba hãng giả lập
  dùng lúc nhận bảng kê: chính sách giả định để trình diễn đồng hồ đếm ngược, không phải quy định thật.
- Căn cứ tham khảo (công khai, không phải dữ liệu thật của hãng nào): công thức đối soát và phí chuyển hoàn của GHN,
  cách hiểu "trả trước" của GHTK. Xem docs/reuse-and-data.md.
- `status_policy`: theo trạng thái đơn (common.enums.OrderStatus), khoản nào được tính:
  - `collect_cod`: hãng chuyển lại tiền thu hộ. `charge_shipping`: tính phí giao hàng cùng
    bảo hiểm, lưu kho, đổi địa chỉ, đồng kiểm. `charge_return`: tính phí chuyển hoàn.
  - Hoàn hàng (RETURNED, không giao được): không có thu hộ, tính phí giao và phí hoàn.
  - Trả hàng (RETURN_BY_CUSTOMER, người mua trả sau khi đã nhận): thu hộ vẫn chuyển, tính thêm phí hoàn.
  - Hàng lỗi (DEFECTIVE): không có thu hộ; Carrier A miễn phí hoàn, B và C tính.
  - Thất lạc (LOST): không tính khoản nào (bồi thường nằm ngoài công thức đối soát).
"""
RULES_VERSION = 1
RULES_UPDATED_AT = "2026-10-22T00:00:00+07:00"

CARRIER_PARAMS: dict[str, dict] = {
    "carrier_a": {
        "display_name": "Carrier A",
        "dim_weight_divisor": 6000,
        "rate_table": [
            {
                "region": "noi_tinh",
                "brackets": [
                    {"max_weight_g": 500, "fee": 22_000},
                    {"max_weight_g": 1_000, "fee": 25_000},
                    {"max_weight_g": 2_000, "fee": 30_000},
                    {"max_weight_g": 3_000, "fee": 35_000},
                ],
                "extra_step_g": 500,
                "extra_fee": 2_500,
            },
            {
                "region": "noi_vung",
                "brackets": [
                    {"max_weight_g": 500, "fee": 28_000},
                    {"max_weight_g": 1_000, "fee": 32_000},
                    {"max_weight_g": 2_000, "fee": 38_000},
                    {"max_weight_g": 3_000, "fee": 44_000},
                ],
                "extra_step_g": 500,
                "extra_fee": 3_500,
            },
            {
                "region": "lien_vung",
                "brackets": [
                    {"max_weight_g": 500, "fee": 32_000},
                    {"max_weight_g": 1_000, "fee": 37_000},
                    {"max_weight_g": 2_000, "fee": 45_000},
                    {"max_weight_g": 3_000, "fee": 52_000},
                ],
                "extra_step_g": 500,
                "extra_fee": 5_000,
            },
        ],
        "surcharges": {
            "insurance": {"rate_bp": 100, "min_declared_value": 300_000},
            "return": {"rate_bp": 5_000, "fixed": 0},
            "storage": {"per_day": 3_000, "free_days": 3},
            "address_change": {"fixed": 10_000},
            "inspection": {"fixed": 3_000},
        },
        "transfer_fee": 1_650,
        "transfer_fee_cod_only": True,
        "cod_payout_days": 2,
        "claim_window_hours": 168,
        "claim_deadline_anchor": "statement_received_at",
        "status_policy": {
            "DELIVERED": {"collect_cod": True, "charge_shipping": True, "charge_return": False},
            "RETURNED": {"collect_cod": False, "charge_shipping": True, "charge_return": True},
            "RETURN_BY_CUSTOMER": {"collect_cod": True, "charge_shipping": True, "charge_return": True},
            "DEFECTIVE": {"collect_cod": False, "charge_shipping": True, "charge_return": False},
            "LOST": {"collect_cod": False, "charge_shipping": False, "charge_return": False},
        },
    },
    "carrier_b": {
        "display_name": "Carrier B",
        "dim_weight_divisor": 5000,
        "rate_table": [
            {
                "region": "noi_tinh",
                "brackets": [
                    {"max_weight_g": 1_000, "fee": 24_000},
                    {"max_weight_g": 3_000, "fee": 30_000},
                    {"max_weight_g": 5_000, "fee": 38_000},
                ],
                "extra_step_g": 1_000,
                "extra_fee": 4_000,
            },
            {
                "region": "noi_vung",
                "brackets": [
                    {"max_weight_g": 1_000, "fee": 30_000},
                    {"max_weight_g": 3_000, "fee": 36_000},
                    {"max_weight_g": 5_000, "fee": 46_000},
                ],
                "extra_step_g": 1_000,
                "extra_fee": 5_000,
            },
            {
                "region": "lien_vung",
                "brackets": [
                    {"max_weight_g": 1_000, "fee": 33_000},
                    {"max_weight_g": 3_000, "fee": 42_000},
                    {"max_weight_g": 5_000, "fee": 55_000},
                ],
                "extra_step_g": 1_000,
                "extra_fee": 7_000,
            },
        ],
        "surcharges": {
            "insurance": {"rate_bp": 50, "min_declared_value": 1_000_000},
            "return": {"rate_bp": 10_000, "fixed": 0},
            "storage": {"per_day": 4_000, "free_days": 2},
            "address_change": {"fixed": 15_000},
            "inspection": {"fixed": 0},
        },
        "transfer_fee": 0,
        "transfer_fee_cod_only": True,
        "cod_payout_days": 3,
        "claim_window_hours": 72,
        "claim_deadline_anchor": "statement_received_at",
        "status_policy": {
            "DELIVERED": {"collect_cod": True, "charge_shipping": True, "charge_return": False},
            "RETURNED": {"collect_cod": False, "charge_shipping": True, "charge_return": True},
            "RETURN_BY_CUSTOMER": {"collect_cod": True, "charge_shipping": True, "charge_return": True},
            "DEFECTIVE": {"collect_cod": False, "charge_shipping": True, "charge_return": True},
            "LOST": {"collect_cod": False, "charge_shipping": False, "charge_return": False},
        },
    },
    "carrier_c": {
        "display_name": "Carrier C",
        "dim_weight_divisor": 6000,
        "rate_table": [
            {
                "region": "noi_tinh",
                "brackets": [
                    {"max_weight_g": 500, "fee": 20_000},
                    {"max_weight_g": 1_000, "fee": 24_000},
                    {"max_weight_g": 2_000, "fee": 29_500},
                ],
                "extra_step_g": 500,
                "extra_fee": 3_000,
            },
            {
                "region": "noi_vung",
                "brackets": [
                    {"max_weight_g": 500, "fee": 25_000},
                    {"max_weight_g": 1_000, "fee": 29_000},
                    {"max_weight_g": 2_000, "fee": 34_000},
                ],
                "extra_step_g": 500,
                "extra_fee": 4_000,
            },
            {
                "region": "lien_vung",
                "brackets": [
                    {"max_weight_g": 500, "fee": 29_000},
                    {"max_weight_g": 1_000, "fee": 33_000},
                    {"max_weight_g": 2_000, "fee": 38_000},
                ],
                "extra_step_g": 500,
                "extra_fee": 5_500,
            },
        ],
        "surcharges": {
            "insurance": {"rate_bp": 80, "min_declared_value": 500_000},
            "return": {"rate_bp": 0, "fixed": 15_000},
            "storage": {"per_day": 2_000, "free_days": 5},
            "address_change": {"fixed": 12_000},
            "inspection": {"fixed": 5_000},
        },
        "transfer_fee": 1_100,
        "transfer_fee_cod_only": True,
        "cod_payout_days": 1,
        "claim_window_hours": 24,
        "claim_deadline_anchor": "statement_received_at",
        "status_policy": {
            "DELIVERED": {"collect_cod": True, "charge_shipping": True, "charge_return": False},
            "RETURNED": {"collect_cod": False, "charge_shipping": True, "charge_return": True},
            "RETURN_BY_CUSTOMER": {"collect_cod": True, "charge_shipping": True, "charge_return": True},
            "DEFECTIVE": {"collect_cod": False, "charge_shipping": True, "charge_return": True},
            "LOST": {"collect_cod": False, "charge_shipping": False, "charge_return": False},
        },
    },
}


def carrier_rule_documents() -> list[dict]:
    """Các document `carrier_rules` (khớp contracts/schemas/carrier_rules.json) để đổ vào Mongo."""
    return [
        {"carrier": carrier, "version": RULES_VERSION, **params, "updated_at": RULES_UPDATED_AT}
        for carrier, params in CARRIER_PARAMS.items()
    ]
