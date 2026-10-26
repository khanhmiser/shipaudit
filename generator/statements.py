"""[B] Xuất 3 file bảng kê thô theo 3 định dạng (xem contracts/samples/).

Mỗi hãng một định dạng, có cột riêng cho một số khoản; khoản không có cột riêng được hãng gộp:
- Carrier A (CSV ","): order_code,cod_amount,ship_fee,insurance,return_fee,transfer_fee,net_paid
  `ship_fee` gộp phí giao + lưu kho + đổi địa chỉ + đồng kiểm.
- Carrier B (CSV ";"): ma_don;thu_ho;cuoc_van_chuyen;phi_hoan;phi_luu_kho;thuc_tra
  `cuoc_van_chuyen` gộp phí giao + bảo hiểm + đổi địa chỉ + đồng kiểm + chuyển khoản.
- Carrier C (CSV ","): tracking,cod,total_fee,note,net
  `total_fee` gộp mọi khoản trừ; `note` ghi trạng thái (hoan, tra hang, hang loi, doi dia chi...).
Cột tiền thực nhận (net_paid / thuc_tra / net) đã gồm cả các khoản cộng (trả trước, khuyến mãi...).

`normalize_row` là cách đổi một dòng thô về schema statement_lines (bản tham chiếu cho parser
của A): khoản gộp ghi vào `shipping_fee`, khoản không có cột thì không ghi trường đó.
"""
from __future__ import annotations

import csv
import io
from datetime import timedelta

from contracts.interfaces import Breakdown
from core.periods import period_bounds, to_iso

ISSUE_HOUR = 9  # hãng gửi bảng kê lúc 9:00 thứ Hai sau kỳ (giờ Việt Nam)

FORMATS: dict[str, dict] = {
    "carrier_a": {
        "delimiter": ",",
        "columns": ["order_code", "cod_amount", "ship_fee", "insurance", "return_fee", "transfer_fee", "net_paid"],
        "fields": {
            "order_code": "order_code", "cod_amount": "cod_collected", "ship_fee": "shipping_fee",
            "insurance": "insurance_fee", "return_fee": "return_shipping_fee", "transfer_fee": "transfer_fee",
            "net_paid": "net_paid",
        },
    },
    "carrier_b": {
        "delimiter": ";",
        "columns": ["ma_don", "thu_ho", "cuoc_van_chuyen", "phi_hoan", "phi_luu_kho", "thuc_tra"],
        "fields": {
            "ma_don": "order_code", "thu_ho": "cod_collected", "cuoc_van_chuyen": "shipping_fee",
            "phi_hoan": "return_shipping_fee", "phi_luu_kho": "storage_fee", "thuc_tra": "net_paid",
        },
    },
    "carrier_c": {
        "delimiter": ",",
        "columns": ["tracking", "cod", "total_fee", "note", "net"],
        "fields": {"tracking": "order_code", "cod": "cod_collected", "total_fee": "shipping_fee", "net": "net_paid"},
    },
}
NOTES_C = {"RETURNED": "hoan", "RETURN_BY_CUSTOMER": "tra hang", "DEFECTIVE": "hang loi", "LOST": "that lac"}


def statement_id_for(carrier: str, period: str) -> str:
    return f"STM-{carrier[-1].upper()}-{period.replace('-', '')}"


def issued_at(period: str):
    return period_bounds(period)[1] + timedelta(hours=ISSUE_HOUR)


def render_row(carrier: str, order: dict, actual: Breakdown) -> dict[str, str]:
    """Một dòng thô của bảng kê, từ các khoản hãng thực tính (`actual`)."""
    a = actual
    net = a.expected_amount
    if carrier == "carrier_a":
        values = [
            order["order_code"], a.cod_collected,
            a.shipping_fee + a.storage_fee + a.address_change_fee + a.inspection_fee,
            a.insurance_fee, a.return_shipping_fee, a.transfer_fee, net,
        ]
    elif carrier == "carrier_b":
        values = [
            order["order_code"], a.cod_collected,
            a.shipping_fee + a.insurance_fee + a.address_change_fee + a.inspection_fee + a.transfer_fee,
            a.return_shipping_fee, a.storage_fee, net,
        ]
    elif carrier == "carrier_c":
        notes = [NOTES_C[order["status"]]] if order["status"] in NOTES_C else []
        if order.get("address_changes"):
            notes.append("doi dia chi")
        total = (a.shipping_fee + a.insurance_fee + a.return_shipping_fee + a.storage_fee
                 + a.address_change_fee + a.inspection_fee + a.transfer_fee)
        values = [order["order_code"], a.cod_collected, total, ", ".join(notes), net]
    else:
        raise ValueError(f"không có định dạng bảng kê cho {carrier}")
    return dict(zip(FORMATS[carrier]["columns"], (str(v) for v in values)))


def normalize_row(carrier: str, row: dict[str, str]) -> dict:
    """Dòng thô → các trường của statement_lines (chưa có statement_id, period, ingested_at)."""
    out: dict = {"carrier": carrier}
    for column, field in FORMATS[carrier]["fields"].items():
        value = row[column].strip()
        out[field] = value if field == "order_code" else int(value)
    out["raw"] = dict(row)
    return out


def to_csv(carrier: str, rows: list[dict[str, str]]) -> str:
    fmt = FORMATS[carrier]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fmt["columns"], delimiter=fmt["delimiter"], lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def build_statements(placements: list[dict], periods: list[str]) -> tuple[dict[str, str], list[dict]]:
    """placements: [{order, actual: Breakdown, period}] (period None = không có trong bảng kê nào).

    Trả về ({tên file: nội dung CSV}, statement_lines đã chuẩn hóa).
    """
    rows: dict[tuple[str, str], list[tuple[dict, dict]]] = {
        (c, p): [] for c in FORMATS for p in periods
    }
    for pl in placements:
        if pl["period"] is None:
            continue
        carrier = pl["order"]["carrier"]
        rows[(carrier, pl["period"])].append((pl["order"], render_row(carrier, pl["order"], pl["actual"])))

    files: dict[str, str] = {}
    lines: list[dict] = []
    for (carrier, period), items in rows.items():
        items.sort(key=lambda x: x[0]["order_code"])
        sid = statement_id_for(carrier, period)
        files[f"{sid}.csv"] = to_csv(carrier, [r for _, r in items])
        received = to_iso(issued_at(period))
        for _, raw in items:
            line = normalize_row(carrier, raw)
            line.update(statement_id=sid, period=period, ingested_at=received)
            lines.append(line)
    return files, lines
