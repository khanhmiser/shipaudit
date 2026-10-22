"""[B] Xuất bảng kê thô theo 3 định dạng (khớp contracts/samples/), dòng bảng kê đã chuẩn hóa,
sự kiện nạp (ingest_events) và nhãn đáp án.

Lưu ý về bảng kê thô:
- Cột "net" luôn là số thực nhận cuối cùng. Khoản "shop trả trước" được cộng lại trong net nhưng
  không có cột riêng (giống bảng kê thật: shop chỉ thấy số cuối), nên cần so với orders.prepaid_by_shop.
- Carrier C gộp bảo hiểm + phí hoàn vào total_fee; đổi địa chỉ trừ ngoài total_fee (ghi chú "doi dia chi").
  Khi chuẩn hóa, shipping_fee của Carrier C = total_fee, các cột phí khác của dòng này = 0.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from generator.carriers.params import CARRIER_PARAMS
from generator.synthetic import VN_TZ, iso_label

# Giờ trước `now` mà bảng kê kỳ mới nhất của từng hãng được nhận (để demo đồng hồ khiếu nại).
LATEST_RECEIVED_HOURS_AGO = {"carrier_c": 6, "carrier_a": 20, "carrier_b": 40}
BATCH_SIZE = 25


def statement_id(carrier: str, monday: date) -> str:
    prefix = CARRIER_PARAMS[carrier]["prefix"]
    iso = monday.isocalendar()
    return f"ST-{prefix}-{iso.year}W{iso.week:02d}"


def statement_times(carrier: str, monday: date, is_latest: bool, now: datetime) -> tuple[datetime, datetime]:
    """(paid_at, ingested_at) dạng UTC. paid_at = cuối kỳ + cod_payout_days, 10:00 giờ VN."""
    rule = CARRIER_PARAMS[carrier]
    period_end = monday + timedelta(days=6)
    paid_local = datetime(period_end.year, period_end.month, period_end.day, 10, tzinfo=VN_TZ) + timedelta(
        days=rule["cod_payout_days"]
    )
    paid_at = paid_local.astimezone(timezone.utc)
    if is_latest:
        ingested = now.astimezone(timezone.utc) - timedelta(hours=LATEST_RECEIVED_HOURS_AGO[carrier])
    else:
        ingested = (paid_local + timedelta(days=1, hours=-1)).astimezone(timezone.utc)
    if ingested <= paid_at:
        ingested = paid_at + timedelta(hours=1)
    return paid_at, ingested


def _csv_row(carrier: str, order: dict, plan: dict) -> tuple[str, dict]:
    c = plan["comp"]
    code = order["order_code"]
    if carrier == "carrier_a":
        raw = {
            "order_code": code,
            "cod_amount": c["cod"],
            "ship_fee": c["ship"],
            "insurance": c["ins"],
            "return_fee": c["ret"],
            "transfer_fee": c["xfer"],
            "net_paid": plan["net_paid"],
        }
        return ",".join(str(v) for v in raw.values()), raw
    if carrier == "carrier_b":
        raw = {
            "ma_don": code,
            "thu_ho": c["cod"],
            "cuoc_van_chuyen": c["ship"],
            "phi_hoan": c["ret"],
            "phi_luu_kho": c["stor"],
            "thuc_tra": plan["net_paid"],
        }
        return ";".join(str(v) for v in raw.values()), raw
    notes = []
    if c["addr"] > 0:
        notes.append("doi dia chi")
    if order["status"] == "DEFECTIVE":
        notes.append("hang loi")
    elif order["status"] == "RETURNED":
        notes.append("hoan")
    elif order["status"] == "RETURN_BY_CUSTOMER":
        notes.append("tra hang")
    note = "; ".join(notes)
    total_fee = c["ship"] + c["ins"] + c["ret"]
    raw = {"tracking": code, "cod": c["cod"], "total_fee": total_fee, "note": note, "net": plan["net_paid"]}
    note_cell = f'"{note}"' if note else ""
    return f'{code},{c["cod"]},{total_fee},{note_cell},{plan["net_paid"]}', raw


RAW_HEADERS = {
    "carrier_a": "order_code,cod_amount,ship_fee,insurance,return_fee,transfer_fee,net_paid",
    "carrier_b": "ma_don;thu_ho;cuoc_van_chuyen;phi_hoan;phi_luu_kho;thuc_tra",
    "carrier_c": "tracking,cod,total_fee,note,net",
}


def _normalized(carrier: str, sid: str, period: str, order: dict, plan: dict, raw: dict, paid_at, ingested_at) -> dict:
    c = plan["comp"]
    if carrier == "carrier_c":
        shipping, insurance, ret = c["ship"] + c["ins"] + c["ret"], 0, 0
    else:
        shipping, insurance, ret = c["ship"], c["ins"], c["ret"]
    return {
        "statement_id": sid,
        "carrier": carrier,
        "order_code": order["order_code"],
        "period": period,
        "cod_collected": c["cod"],
        "shipping_fee": shipping,
        "insurance_fee": insurance,
        "return_shipping_fee": ret,
        "storage_fee": c["stor"],
        "address_change_fee": c["addr"],
        "inspection_fee": c["insp"],
        "promotion": 0,
        "transfer_fee": c["xfer"],
        "net_paid": plan["net_paid"],
        "raw": raw,
        "ingested_at": ingested_at,
        "paid_at": paid_at,  # trường mở rộng (đề xuất contract v0.2.0)
    }


def build_statements(
    rng: random.Random, orders: list[dict], plans: list[dict], mondays: list[date], now: datetime
) -> dict:
    """Gom dòng theo (hãng, kỳ xuất hiện). Trả về các file thô, dòng chuẩn hóa, sự kiện nạp, nhãn."""
    by_code = {o["order_code"]: o for o in orders}
    last_week = len(mondays) - 1
    groups: dict[tuple[str, int], list[dict]] = {}
    for plan in plans:
        if plan["present"]:
            groups.setdefault((plan["carrier"], plan["appear_week"]), []).append(plan)

    raw_files: dict[str, str] = {}
    lines: list[dict] = []
    events: list[dict] = []
    meta: dict[str, dict] = {}

    for week_idx, monday in enumerate(mondays):
        period = iso_label(monday)
        for carrier in sorted(CARRIER_PARAMS):
            sid = statement_id(carrier, monday)
            paid_at, ingested_at = statement_times(carrier, monday, week_idx == last_week, now)
            group = sorted(groups.get((carrier, week_idx), []), key=lambda p: p["order_code"])
            csv_lines = [RAW_HEADERS[carrier]]
            for plan in group:
                order = by_code[plan["order_code"]]
                row_text, raw = _csv_row(carrier, order, plan)
                csv_lines.append(row_text)
                lines.append(_normalized(carrier, sid, period, order, plan, raw, paid_at, ingested_at))
            raw_files[f"statement_{carrier}_{monday.isocalendar().year}W{monday.isocalendar().week:02d}.csv"] = (
                "\n".join(csv_lines) + "\n"
            )
            meta[sid] = {"carrier": carrier, "period": period, "rows": len(group), "paid_at": paid_at, "ingested_at": ingested_at}

            # Sự kiện nạp theo lô BATCH_SIZE dòng.
            remaining = len(group)
            k = 0
            while remaining > 0:
                size = min(BATCH_SIZE, remaining)
                ts = ingested_at + timedelta(seconds=3 * k)
                events.append(
                    {
                        "ts": ts,
                        "meta": {"carrier": carrier, "statement_id": sid},
                        "rows": size,
                        "duration_ms": int(size * rng.uniform(4, 10)),
                        "lag_seconds": round(rng.uniform(0.5, 6.0) + 0.2 * k, 2),
                        "status": "PARTIAL" if rng.random() < 0.015 else "OK",
                    }
                )
                remaining -= size
                k += 1

    label_lines = []
    excluded = []
    for plan in plans:
        order = by_code[plan["order_code"]]
        sid = statement_id(plan["carrier"], mondays[plan["appear_week"]])
        label_lines.append(
            {
                "statement_id": sid,
                "order_code": plan["order_code"],
                "carrier": plan["carrier"],
                "status": order["status"],
                "diff_type": plan["diff_type"],
                "subtype": plan["subtype"],
                "incident": plan["incident"],
                "present_in_statement": plan["present"],
                "delivery_period": iso_label(mondays[plan["delivery_week"]]),
                "expected_amount": plan["expected"],
                "actual_amount": plan["net_paid"],
                "diff": plan["diff"],
                "breakdown": plan["breakdown"],
            }
        )
    plan_codes = {p["order_code"] for p in plans}
    for o in orders:
        if o["order_code"] not in plan_codes:
            excluded.append({"order_code": o["order_code"], "carrier": o["carrier"], "status": o["status"], "reason": "LOST_NO_STATEMENT_ROW"})

    events.sort(key=lambda e: e["ts"])
    return {"raw_files": raw_files, "lines": lines, "events": events, "labels": label_lines, "excluded": excluded, "meta": meta}
