"""[B] Sinh 100% đơn hàng tổng hợp (không dùng dữ liệu thật, không phụ thuộc Olist).

Phân phối giá trị đơn, khối lượng, kích thước, tỷ lệ COD/hoàn/trả/lỗi là GIẢ ĐỊNH của đội,
chưa hiệu chỉnh theo dataset nào. Dữ liệu chỉ chứng minh hệ thống chạy đúng và tái lập được,
không phản ánh tỷ lệ thực tế của thị trường.
"""
from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta, timezone

from generator import fee_model
from generator.carriers.params import CARRIER_PARAMS, CARRIER_WEEKLY_ORDERS, REGIONS

VN_TZ = timezone(timedelta(hours=7))

REGION_WEIGHTS = (0.30, 0.30, 0.40)
STATUS_CHOICES = (
    ("DELIVERED", 0.875),
    ("RETURNED", 0.070),
    ("RETURN_BY_CUSTOMER", 0.030),
    ("DEFECTIVE", 0.020),
    ("LOST", 0.005),
)
COD_SHARE = 0.70
PREPAID_SHARE_OF_NON_COD = 0.70


def week_starts(now: datetime, weeks: int) -> list[date]:
    """Các thứ Hai (giờ VN) của `weeks` tuần ISO đã kết thúc ngay trước `now`, tăng dần."""
    today = now.astimezone(VN_TZ).date()
    this_monday = today - timedelta(days=today.weekday())
    return [this_monday - timedelta(days=7 * k) for k in range(weeks, 0, -1)]


def iso_label(monday: date) -> str:
    iso = monday.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _pick(rng: random.Random, choices):
    r = rng.random()
    acc = 0.0
    for value, p in choices:
        acc += p
        if r < acc:
            return value
    return choices[-1][0]


def _dimensions(rng: random.Random, weight_g: int) -> tuple[int, int, int]:
    volume = weight_g * rng.uniform(3.0, 14.0)
    base = volume ** (1 / 3)
    length = base * rng.uniform(1.0, 1.8)
    width = base * rng.uniform(0.7, 1.2)
    height = volume / (length * width)
    clip = lambda v: int(min(120, max(1, round(v))))  # noqa: E731
    return clip(length), clip(width), clip(height)


def make_orders(rng: random.Random, now: datetime, weeks: int = 8) -> list[dict]:
    """Trả về danh sách đơn đúng contracts/schemas/orders.json (+ vài trường mở rộng, + `_week`)."""
    mondays = week_starts(now, weeks)
    counters = {c: 0 for c in CARRIER_PARAMS}
    orders: list[dict] = []
    for week_idx, monday in enumerate(mondays):
        for carrier in sorted(CARRIER_PARAMS):
            rule = CARRIER_PARAMS[carrier]
            n = int(CARRIER_WEEKLY_ORDERS[carrier] * rng.uniform(0.9, 1.1))
            for _ in range(n):
                counters[carrier] += 1
                order = _make_order(rng, carrier, rule, counters[carrier], monday)
                order["_week"] = week_idx
                orders.append(order)
    ceiling = datetime.max.replace(tzinfo=timezone.utc)
    orders.sort(key=lambda o: (o["_week"], o.get("delivered_at") or ceiling, o["order_code"]))
    return orders


def _make_order(rng: random.Random, carrier: str, rule: dict, seq: int, monday: date) -> dict:
    weight_g = int(min(20000, max(50, round(rng.lognormvariate(math.log(550), 0.75) / 10) * 10)))
    length, width, height = _dimensions(rng, weight_g)
    value = int(min(6_000_000, max(30_000, round(rng.lognormvariate(math.log(260_000), 0.8) / 1000) * 1000)))
    is_cod = rng.random() < COD_SHARE
    status = _pick(rng, STATUS_CHOICES)
    region = _pick(rng, tuple(zip(REGIONS, REGION_WEIGHTS)))
    s = rule["surcharges"]

    storage_days = 0
    if s["storage_per_day"] > 0:
        if status == "RETURNED" and rng.random() < 0.30:
            storage_days = rng.randint(2, 5)
        elif rng.random() < 0.06:
            storage_days = rng.randint(3, 6)
    address_changed = bool(s["address_change"]) and rng.random() < 0.025

    order = {
        "order_code": f"{rule['prefix']}-{seq:04d}",
        "carrier": carrier,
        "region": region,
        "weight_g": weight_g,
        "length_cm": length,
        "width_cm": width,
        "height_cm": height,
        "cod_amount": value if is_cod else 0,
        "prepaid_by_shop": 0,
        "declared_value": value,
        "status": status,
        "source": "synthetic",
        # Trường mở rộng (đề xuất contract v0.2.0), engine có thể bỏ qua:
        "address_changed": address_changed,
        "inspected": False,
        "storage_days": storage_days,
    }
    if status != "LOST":
        day = rng.randint(0, 5)
        at = datetime(monday.year, monday.month, monday.day, tzinfo=VN_TZ) + timedelta(
            days=day, hours=rng.randint(8, 19), minutes=rng.randint(0, 59)
        )
        order["delivered_at"] = at.astimezone(timezone.utc)
    else:
        order["delivered_at"] = None  # đơn thất lạc: không có ngày hoàn tất
    if not is_cod and rng.random() < PREPAID_SHARE_OF_NON_COD:
        order["prepaid_by_shop"] = fee_model.shipping_fee(order, rule)
    return order
