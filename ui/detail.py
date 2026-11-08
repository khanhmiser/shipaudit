"""[B] Phần thuần của màn Chi tiết đơn (không gọi Streamlit): bảng đối chiếu từng khoản, giải thích vì sao lệch,
nội dung khiếu nại soạn sẵn, đường đi phục hồi và dòng thời gian. Chỉ dùng số liệu đối soát và quy tắc hãng
(không dùng AI để tính tiền hay kết luận). Mọi chuỗi lấy từ dữ liệu đều đi qua view.esc trước khi ghép HTML.
"""
from __future__ import annotations

from datetime import datetime

from core.periods import as_aware
from ui import view
from ui.view import (
    CLAIM_STATUS_LABELS, DIFF_TYPE_LABELS, FORMULA_ITEMS, ORDER_STATUS_LABELS, REGION_LABELS, SOURCE_LABELS, TOTAL,
    badge, breakdown_rows, dt_vn, esc, money_cell, period_label, vnd,
)


# Hãng gộp các khoản này vào tổng cước (bảng kê không có cột riêng): so sánh trên khoản giao hàng đã gộp.
MERGEABLE = {"insurance_fee": "phí bảo hiểm", "return_shipping_fee": "phí chuyển hoàn"}
SHIPPING_LABEL = "Phí giao hàng"
MERGED_SHORT = "Phí giao hàng (gộp)"


def merged_fields(rec: dict) -> list[str]:
    actual = rec.get("actual_breakdown")
    if not actual or "shipping_fee" not in actual:
        return []
    return [f for f in MERGEABLE if f not in actual]


def merge_view(rec: dict) -> tuple[dict, str]:
    """Bản ghi để hiển thị: với hãng gộp phí, cộng các khoản bị gộp vào phí giao hàng phải nhận.
    Trả về (bản ghi, các khoản bị gộp, ghi bằng chữ; rỗng nếu không gộp)."""
    fields = [f for f in merged_fields(rec) if (rec.get("breakdown") or {}).get(f)]
    if not fields:
        return rec, ""
    exp = dict(rec.get("breakdown") or {})
    exp["shipping_fee"] = int(exp.get("shipping_fee", 0)) + sum(int(exp[f]) for f in fields)
    for f in fields:
        exp[f] = 0
    return {**rec, "breakdown": exp}, ", ".join(MERGEABLE[f] for f in fields)


def n(amount: int | float | None) -> str:
    """Số nguyên có dấu chấm ngăn hàng nghìn: 1234567 → "1.234.567"."""
    return "—" if amount is None else f"{int(amount):,}".replace(",", ".")


def breakdown_table(rec: dict, include_zero: bool = False) -> str:
    """Bảng "Đối chiếu số tiền": từng khoản phải nhận (theo quy tắc) so với thực nhận (hãng chuyển)."""
    rows = []
    rec, merged = merge_view(rec)
    for r in breakdown_rows(rec, include_zero):
        sign, total = r["Cộng/Trừ"], r["Khoản"] == TOTAL
        sub = ""
        if merged and r["Khoản"] == SHIPPING_LABEL:
            r = {**r, "Khoản": MERGED_SHORT}
            sub = f'<div class="sa-subtle" style="font-size:12px">hãng gộp cả {esc(merged)}</div>'


        def cell(value, sign=sign, total=total):
            if value is None:
                return '<span class="sa-subtle">—</span>'
            return n(value) if total else f"{'+' if sign == '+' else '−'}{n(value)}"

        diff = r["Chênh lệch"]
        if diff is None:
            diff_cell = '<span class="sa-subtle">—</span>'
        elif diff == 0:
            diff_cell = '<span class="sa-subtle">0</span>'
        else:
            diff_cell = money_cell(diff, bold=True)
        cls = "sa-total" if total else ("sa-hl" if diff else "")
        label = f'<span style="white-space:nowrap">{esc(r["Khoản"])}</span>{sub}'
        rows.append(([label, cell(r["Phải nhận"]), cell(r["Thực nhận"]), diff_cell], cls))
    return view.table([("Khoản", False), ("Phải nhận", True), ("Thực nhận", True), ("Lệch", True)], rows, 520)


def fee_derivation(order: dict | None, rule) -> str | None:
    """Cách quy tắc hãng ra phí giao hàng của đơn (khối lượng tính cước, vùng). None nếu thiếu dữ liệu."""
    if not order or rule is None or not order.get("weight_g") or order.get("region") not in rule.rates:
        return None
    length, width, height = (int(order.get(k) or 0) for k in ("length_cm", "width_cm", "height_cm"))
    real = int(order["weight_g"])
    dim = rule.dim_weight_g(length, width, height)
    charge = max(real, dim)
    return (f"Phí giao hàng theo quy tắc {rule.display_name} (giả định): vùng {REGION_LABELS.get(order['region'], order['region'])}, "
            f"khối lượng tính cước = lớn hơn của {n(real)} g (cân thật) và {n(dim)} g (quy đổi: {length}×{width}×{height} cm "
            f"÷ {n(rule.dim_weight_divisor)}) = {n(charge)} g, ra {n(rule.shipping_fee(order['region'], charge))} ₫.")


def why_diff(rec: dict, order: dict | None, rule, names: dict[str, str] | None = None) -> dict:
    """Giải thích vì sao số phải nhận khác số thực nhận, chỉ từ quy tắc và bảng kê.

    Trả về {"lines": [câu...], "pair": [(nhãn, khoản theo quy tắc, khoản hãng ghi)...], "note": cách tính theo quy tắc}."""
    kind = rec.get("diff_type", "NONE")
    carrier = (names or {}).get(rec.get("carrier"), rec.get("carrier"))
    merged = merged_fields(rec)
    original = rec.get("breakdown") or {}
    rec, merged_text = merge_view(rec)
    ship_label = f"{SHIPPING_LABEL} (gộp {merged_text})" if merged_text else SHIPPING_LABEL
    expected, actual = rec.get("breakdown") or {}, rec.get("actual_breakdown")
    diff = int(rec.get("diff", 0))
    lines: list[str] = []
    pair: list[tuple[str, int, int]] = []
    changed = [
        (ship_label if f == "shipping_fee" else label, int(expected.get(f, 0)), int(actual[f]), sign)
        for f, label, sign in FORMULA_ITEMS
        if actual and f in actual and f != "prepaid_by_shop" and int(expected.get(f, 0)) != int(actual[f])
    ]
    if rec.get("unmatched"):
        lines.append(f"Dòng bảng kê của {carrier} không khớp đơn nào của doanh nghiệp, cần người kiểm tra.")
    elif kind == "NONE":
        lines.append("Số tiền thực nhận khớp số tiền phải nhận theo quy tắc của hãng.")
    elif kind == "MISSING_IN_STATEMENT":
        when = f" ngày {dt_vn(rec.get('delivered_at'))}" if rec.get("delivered_at") else ""
        lines.append(f"Đơn đã giao{when} và thuộc bảng kê {period_label(rec.get('period'))}, nhưng bảng kê của {carrier} "
                     f"không có dòng nào cho đơn này. Số tiền phải nhận {vnd(rec.get('expected_amount'))}, thực nhận 0 ₫.")
    elif kind == "LATE_PAYOUT":
        lines.append(f"Số tiền khớp quy tắc nhưng đơn chỉ xuất hiện ở bảng kê {period_label(rec.get('period'))}, "
                     "kỳ sau kỳ đáng ra phải chuyển. Đây là chuyển tiền chậm, không thiếu tiền.")
    elif kind == "COD_MISMATCH":
        exp_cod = int(expected.get("cod_collected", 0))
        act_cod = int((actual or {}).get("cod_collected", 0))
        lines.append(f"Bảng kê ghi tiền thu hộ {vnd(act_cod)} trong khi đơn thu hộ {vnd(exp_cod)}: "
                     f"hãng ghi thiếu {vnd(exp_cod - act_cod)} tiền thu hộ.")
        pair = [("Tiền thu hộ", exp_cod, act_cod)]
    elif kind == "RETURN_FEE_DOUBLE" and "return_shipping_fee" in merged:
        ref = int(original.get("return_shipping_fee", 0))
        lines.append(f"{carrier} gộp phí chuyển hoàn vào tổng cước nên bảng kê không ghi riêng. "
                     + (f"Phí chuyển hoàn theo quy tắc là {vnd(ref)}; " if ref
                        else "Theo quy tắc, đơn ở trạng thái này không bị tính phí chuyển hoàn; ")
                     + f"tổng cước hãng trừ vượt quy tắc {vnd(diff)}, bằng thêm một lần phí hoàn.")
        pair = [(label, exp, act) for label, exp, act, _ in changed[:1]]
    elif changed:
        for label, exp, act, sign in changed[:4]:
            gap = sign * (exp - act)
            lines.append(f"{label}: quy tắc {vnd(exp)}, hãng ghi {vnd(act)} "
                         f"({'doanh nghiệp nhận thiếu' if gap > 0 else 'doanh nghiệp nhận thừa'} {vnd(abs(gap))}).")
        pair = [(label, exp, act) for label, exp, act, _ in changed[:1]]
    else:
        lines.append(f"Hãng không ghi riêng từng khoản (gộp vào tổng cước). Số tiền thực nhận thấp hơn số tiền "
                     f"phải nhận {vnd(diff)}.")
    note = fee_derivation(order, rule) if kind in ("FEE_MISMATCH", "RETURN_FEE_DOUBLE") else None
    return {"lines": lines, "pair": pair, "note": note}


def why_html(why: dict) -> str:
    body = "".join(f'<p style="margin:0;line-height:1.6">{esc(t)}</p>' for t in why["lines"])
    if why["pair"]:
        label, exp, act = why["pair"][0]
        label = MERGED_SHORT if label.startswith(f"{SHIPPING_LABEL} (gộp") else label
        body += (f'<div class="sa-pair"><div><div class="sa-kpi-l">Theo quy tắc</div><div class="sa-mono">{esc(label)}: '
                 f'<b>{n(exp)}</b></div></div><div class="bad"><div class="sa-kpi-l">Hãng ghi</div>'
                 f'<div class="sa-mono">{esc(label)}: <b>{n(act)}</b></div></div></div>')
    if why["note"]:
        body += f'<div class="sa-subtle" style="font-size:12px">{esc(why["note"])}</div>'
    return f'<div class="sa-stack" style="gap:14px">{body}</div>'


def claim_window_text(rule, names: dict[str, str], carrier: str) -> str:
    if rule is None:
        return ""
    anchor = ("kể từ ngày giao đơn" if rule.claim_deadline_anchor == "delivered_at"
              else "kể từ khi doanh nghiệp nhận bảng kê")
    return f"{names.get(carrier, carrier)} cho {rule.claim_window_hours} giờ {anchor} (quy định giả định của hãng giả lập)."


def claim_message(rec: dict, why: dict, carrier_name: str) -> str:
    """Nội dung khiếu nại soạn sẵn từ số liệu đối soát. Người dùng sửa, tải về hoặc sao chép; ShipAudit không tự gửi hãng."""
    reasons = "\n".join(f"- {t}" for t in why["lines"])
    return (
        f"Kính gửi {carrier_name},\n\n"
        f"Doanh nghiệp đề nghị đối soát lại đơn {rec['order_code']} (bảng kê {rec['statement_id']}, "
        f"{period_label(rec.get('period'))}).\n{reasons}\n\n"
        f"Số tiền phải nhận theo quy tắc: {vnd(rec.get('expected_amount'))}. "
        f"Số tiền thực nhận: {vnd(rec.get('actual_amount'))}. Chênh lệch: {vnd(rec.get('diff'))}.\n"
        f"Đề nghị hoàn lại {vnd(rec.get('diff'))} trong hạn khiếu nại ({dt_vn(rec.get('claim_deadline_at'))}).\n\n"
        "Trân trọng."
    )


def recovery_steps(rec: dict, claim: dict | None) -> list[dict]:
    """Đường đi phục hồi của một khoản: {title, sub, state}, state là done | now | wait."""
    status = claim["status"] if claim else None
    if not (rec.get("diff", 0) > 0 and rec.get("diff_type") != "NONE"):
        return [{"title": "Phát hiện", "sub": "Đối soát khớp hoặc không thiếu tiền, không cần khiếu nại", "state": "done"}]
    step3 = {None: ("Chưa soạn", "now"), "DRAFT": ("Nháp, chờ duyệt", "now"),
             "APPROVED": ("Đã duyệt, chờ gửi hãng", "now"), "EXPIRED": ("Quá hạn khiếu nại", "wait")
             }.get(status, ("Đã gửi hãng", "done"))
    recovered = vnd((claim or {}).get("recovered_amount", 0))
    reason = (claim or {}).get("note") or "chưa ghi lý do"
    follow = len((claim or {}).get("followups") or [])
    step4 = {"SUBMITTED": ("Chờ hãng phản hồi", "now"), "RECOVERED": (f"Đã thu hồi {recovered}", "done"),
             "REJECTED": (f"Hãng từ chối ({reason}); doanh nghiệp tự liên hệ, {follow} lần theo dõi", "now"),
             }.get(status, ("Chờ", "wait"))
    return [
        {"title": "Phát hiện", "sub": f"Đối soát bắt chênh lệch {vnd(rec['diff'])}", "state": "done"},
        {"title": "Điều tra", "sub": "Đối chiếu từng khoản với quy tắc hãng", "state": "done"},
        {"title": "Khiếu nại", "sub": step3[0], "state": step3[1]},
        {"title": "Hãng hoàn tiền", "sub": step4[0], "state": step4[1]},
        {"title": "Kỳ sau khớp", "sub": "Chờ", "state": "wait"},
    ]


def steps_html(steps: list[dict]) -> str:
    items = []
    for s in steps:
        pin = {"done": "", "now": " now", "wait": " wait"}[s["state"]]
        title_cls = "sa-primary" if s["state"] == "now" else ("sa-muted" if s["state"] == "wait" else "")
        items.append(f'<li><span class="sa-pin{pin}"></span><div><div class="{title_cls}" style="font-weight:600">'
                     f'{esc(s["title"])}</div><div class="sa-muted" style="font-size:13px">{esc(s["sub"])}</div></div></li>')
    return f'<ol class="sa-tl">{"".join(items)}</ol>'


def timeline_events(rec: dict, order: dict | None, lines: list[dict], claim: dict | None, now: datetime) -> list[dict]:
    """Dòng thời gian từ dữ liệu thật của đơn: giao, nhận bảng kê, đối soát, claim, hạn khiếu nại."""
    ev: list[dict] = []
    if order and order.get("delivered_at"):
        ev.append({"at": order["delivered_at"], "badge": "Đơn", "tone": "info",
                   "text": f"Đơn ở trạng thái {ORDER_STATUS_LABELS.get(order['status'], order['status']).lower()}."})
    for ln in lines:
        if ln.get("statement_id") == rec["statement_id"] and ln.get("ingested_at"):
            ev.append({"at": ln["ingested_at"], "badge": "Bảng kê", "tone": "accent",
                       "text": f"Nhận bảng kê {ln['statement_id']}; hãng ghi thực nhận {vnd(ln.get('net_paid'))}."})
    if rec.get("updated_at"):
        ev.append({"at": rec["updated_at"], "badge": "Đối soát", "tone": "success",
                   "text": f"{DIFF_TYPE_LABELS.get(rec['diff_type'], rec['diff_type'])}; "
                           f"phải nhận {vnd(rec.get('expected_amount'))}, thực nhận {vnd(rec.get('actual_amount'))}."})
    for h in (claim or {}).get("history", []):
        ev.append({"at": h["at"], "badge": "Claim", "tone": "info",
                   "text": f"{CLAIM_STATUS_LABELS.get(h['status'], h['status'])} · {SOURCE_LABELS.get(h['by'], h['by'])}."})
    if rec.get("claim_deadline_at") and rec.get("diff", 0) > 0:
        past = as_aware(rec["claim_deadline_at"]) <= as_aware(now)
        ev.append({"at": rec["claim_deadline_at"], "badge": "Hạn khiếu nại", "tone": "muted" if past else "warning",
                   "text": "Đã hết hạn khiếu nại." if past else "Hết hạn khiếu nại."})
    return sorted(ev, key=lambda e: as_aware(e["at"]))


def timeline_html(events: list[dict]) -> str:
    items = []
    for e in events:
        items.append(
            f'<li><span class="sa-pin{" warn" if e["tone"] == "warning" else ""}"></span>'
            f'<div style="flex:1 1 auto;min-width:0"><div class="sa-chips"><span class="sa-mono sa-subtle" '
            f'style="font-size:12px">{esc(dt_vn(e["at"]))}</span>{badge(e["badge"], e["tone"])}</div>'
            f'<div style="margin-top:4px">{esc(e["text"])}</div></div></li>')
    return f'<ol class="sa-tl">{"".join(items)}</ol>' if items else '<div class="sa-muted">Chưa có sự kiện nào.</div>'
