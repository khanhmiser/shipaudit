"""[B] Đọc CSV Olist (data/raw/olist/), lấy mẫu 5-20 nghìn đơn, đổi sang VNĐ bằng hệ số cố định,
gán COD ngẫu nhiên có seed. Kiểm tra giấy phép dataset trên Kaggle và ghi vào docs/reuse-and-data.md.

Lấy từ Olist: giá trị hàng (tổng `price` của các món), khối lượng (tổng `product_weight_g`),
kích thước (món lớn nhất), vùng giao (bang người bán so với bang người mua), và trạng thái hủy /
không có hàng làm ứng viên hoàn hàng. Ngày tháng, hãng, thu hộ và phụ phí do generator/orders.py gán.
Trả về cùng dạng "đơn nền" với generator/synthetic.py.
"""
from __future__ import annotations

import csv
import random
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from core.money import to_vnd

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "olist"
BRL_TO_VND = 4_700  # hệ số cố định, giả định cho demo, không phải tỉ giá thật

FILES = {
    "orders": "olist_orders_dataset.csv",
    "items": "olist_order_items_dataset.csv",
    "products": "olist_products_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
}

# Bang của Brazil theo 5 vùng lớn, dùng để quy ra nội vùng / liên vùng.
MACRO_REGION = {
    **dict.fromkeys(["AC", "AM", "AP", "PA", "RO", "RR", "TO"], "N"),
    **dict.fromkeys(["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"], "NE"),
    **dict.fromkeys(["DF", "GO", "MS", "MT"], "CO"),
    **dict.fromkeys(["ES", "MG", "RJ", "SP"], "SE"),
    **dict.fromkeys(["PR", "RS", "SC"], "S"),
}
RETURN_HINT_STATUSES = {"canceled", "unavailable"}


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(float(value)) if value not in (None, "") else default
    except ValueError:
        return default


def region_of(seller_state: str, customer_state: str) -> str:
    if seller_state == customer_state:
        return "noi_tinh"
    if MACRO_REGION.get(seller_state) and MACRO_REGION.get(seller_state) == MACRO_REGION.get(customer_state):
        return "noi_vung"
    return "lien_vung"


def base_orders(rng: random.Random, n: int, data_dir: Path | str = DEFAULT_DIR) -> list[dict]:
    data_dir = Path(data_dir)
    missing = [name for name in FILES.values() if not (data_dir / name).exists()]
    if missing:
        raise FileNotFoundError(
            f"Thiếu file Olist trong {data_dir}: {missing}. Tải dataset từ Kaggle "
            "hoặc chạy --source synthetic."
        )
    orders = _read(data_dir / FILES["orders"])
    products = {p["product_id"]: p for p in _read(data_dir / FILES["products"])}
    customers = {c["customer_id"]: c["customer_state"] for c in _read(data_dir / FILES["customers"])}
    sellers = {s["seller_id"]: s["seller_state"] for s in _read(data_dir / FILES["sellers"])}
    items = defaultdict(list)
    for it in _read(data_dir / FILES["items"]):
        items[it["order_id"]].append(it)

    candidates = sorted(o["order_id"] for o in orders if items.get(o["order_id"]))
    by_id = {o["order_id"]: o for o in orders}
    picked = rng.sample(candidates, min(n, len(candidates)))

    out = []
    for order_id in picked:
        o, its = by_id[order_id], items[order_id]
        prods = [products.get(it["product_id"], {}) for it in its]
        weight = sum(_int(p.get("product_weight_g")) for p in prods)
        dims = max(
            ((_int(p.get("product_length_cm")), _int(p.get("product_width_cm")), _int(p.get("product_height_cm")))
             for p in prods),
            key=lambda d: d[0] * d[1] * d[2],
        )
        goods_brl = sum((Decimal(it.get("price") or "0") for it in its), Decimal(0))
        out.append({
            "region": region_of(sellers.get(its[0]["seller_id"], ""), customers.get(o["customer_id"], "")),
            "weight_g": max(weight, 50),
            "length_cm": dims[0],
            "width_cm": dims[1],
            "height_cm": dims[2],
            "goods_value": max(1_000, to_vnd(goods_brl * BRL_TO_VND / 1_000) * 1_000),
            "status_hint": "RETURNED" if o.get("order_status") in RETURN_HINT_STATUSES else None,
            "source": "olist",
            "source_ref": order_id,
        })
    return out
