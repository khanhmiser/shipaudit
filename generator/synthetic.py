"""[B] Sinh 100% dữ liệu tổng hợp (phương án dự phòng khi không dùng Olist).

Trả về "đơn nền": hàng hóa (khối lượng, kích thước, giá trị) và vùng giao. Phần hãng, trạng thái,
thu hộ, ngày giao gán chung ở generator/orders.py cho cả hai nguồn.
"""
from __future__ import annotations

import random

REGIONS = (("noi_tinh", 35), ("noi_vung", 35), ("lien_vung", 30))


def _round(value: float, step: int) -> int:
    return max(step, int(round(value / step)) * step)


def base_orders(rng: random.Random, n: int) -> list[dict]:
    out = []
    names, weights = zip(*REGIONS)
    for _ in range(n):
        size = rng.random()
        if size < 0.70:
            weight_g = rng.randint(100, 1_500)
            dims = (rng.randint(10, 35), rng.randint(8, 25), rng.randint(2, 15))
        elif size < 0.90:
            weight_g = rng.randint(1_500, 5_000)
            dims = (rng.randint(25, 50), rng.randint(20, 35), rng.randint(10, 30))
        else:
            weight_g = rng.randint(5_000, 15_000)
            dims = (rng.randint(40, 70), rng.randint(30, 50), rng.randint(20, 45))
        goods_value = min(5_000_000, max(30_000, _round(rng.lognormvariate(12.6, 0.7), 1_000)))
        out.append({
            "region": rng.choices(names, weights)[0],
            "weight_g": _round(weight_g, 10),
            "length_cm": dims[0],
            "width_cm": dims[1],
            "height_cm": dims[2],
            "goods_value": goods_value,
            "status_hint": None,
            "source": "synthetic",
        })
    return out
