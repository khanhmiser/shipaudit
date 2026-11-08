"""[B] Phần thuần của màn Chênh lệch (không gọi Streamlit): phân tab, đếm, tìm kiếm, dòng bảng và thanh theo loại.

Tab là bộ lọc, không phải phân hoạch: một khoản có thể vừa "Sắp hết hạn" vừa "Đang khiếu nại" (claim nháp).
Mức khẩn chỉ dựa vào hạn khiếu nại còn lại, không đánh giá hãng.
"""
from __future__ import annotations

from datetime import datetime

from ui import view
from ui.view import esc

TABS = (("all", "Tất cả"), ("soon", "Sắp hết hạn"), ("claiming", "Đang khiếu nại"), ("recovered", "Đã thu hồi"),
        ("rejected", "Bị từ chối"))
CLAIM_TONES = {"DRAFT": "muted", "APPROVED": "info", "SUBMITTED": "accent", "RECOVERED": "success",
               "REJECTED": "danger", "EXPIRED": "muted"}


def claim_status(rec: dict, claims: dict[str, dict]) -> str | None:
    claim = claims.get(rec["reconciliation_id"])
    return claim["status"] if claim else None


def is_claimable(rec: dict, now: datetime) -> bool:
    """Khoản doanh nghiệp nhận thiếu còn trong hạn khiếu nại."""
    hours = view.hours_left(rec.get("claim_deadline_at"), now)
    return rec.get("diff", 0) > 0 and hours is not None and hours > 0


def in_tab(rec: dict, tab: str, claims: dict[str, dict], now: datetime) -> bool:
    status = claim_status(rec, claims)
    if tab == "soon":
        hours = view.hours_left(rec.get("claim_deadline_at"), now)
        return (is_claimable(rec, now) and hours <= view.SOON_HOURS and status in (None, "DRAFT", "APPROVED"))
    if tab == "claiming":
        return status in ("DRAFT", "APPROVED", "SUBMITTED")
    if tab == "recovered":
        return status == "RECOVERED"
    if tab == "rejected":
        return status == "REJECTED"
    return True


def tab_counts(recs: list[dict], claims: dict[str, dict], now: datetime) -> dict[str, int]:
    return {tab: sum(1 for r in recs if in_tab(r, tab, claims, now)) for tab, _ in TABS}


def matches_query(rec: dict, query: str) -> bool:
    q = (query or "").strip().lower()
    return not q or q in rec["order_code"].lower()


def priority(rec: dict, now: datetime) -> tuple:
    """Khoản khiếu nại được và sắp hết hạn lên trước; còn lại theo độ lớn của chênh lệch."""
    if is_claimable(rec, now):
        return (0, view.hours_left(rec["claim_deadline_at"], now), -rec["diff"])
    return (1, 0, -abs(rec.get("diff", 0)))


SORTS = (("urgent", "Gần hạn trước (mặc định)"), ("late_most", "Quá hạn lâu nhất trước"),
         ("late_least", "Quá hạn mới nhất trước"), ("diff_desc", "Chênh lệch lớn nhất trước"),
         ("code_az", "Mã đơn A → Z"), ("code_za", "Mã đơn Z → A"))


def sort_cases(recs: list[dict], sort: str, now: datetime) -> list[dict]:
    """Sắp xếp danh sách. Với kiểu "quá hạn", khoản đã quá hạn lên trước (theo số ngày quá hạn), khoản còn hạn xếp sau."""
    def late_hours(r: dict) -> float:  # > 0: đã quá hạn bấy nhiêu giờ; khoản không có hạn hoặc không thiếu tiền: -inf
        h = view.hours_left(r.get("claim_deadline_at"), now)
        return -h if h is not None and r.get("diff", 0) > 0 else float("-inf")

    if sort == "late_most":
        return sorted(recs, key=lambda r: (-late_hours(r), r["order_code"]))
    if sort == "late_least":
        return sorted(recs, key=lambda r: (late_hours(r) <= 0, late_hours(r), r["order_code"]))
    if sort == "diff_desc":
        return sorted(recs, key=lambda r: (-r.get("diff", 0), r["order_code"]))
    if sort == "code_az":
        return sorted(recs, key=lambda r: r["order_code"].lower())
    if sort == "code_za":
        return sorted(recs, key=lambda r: r["order_code"].lower(), reverse=True)
    return sorted(recs, key=lambda r: priority(r, now))


def level_cell(rec: dict, claims: dict[str, dict], now: datetime) -> str:
    status = claim_status(rec, claims)
    if status:
        return view.badge(view.CLAIM_STATUS_LABELS[status], CLAIM_TONES.get(status, "muted"))
    if rec.get("diff", 0) <= 0:
        return view.badge("Không thiếu tiền", "muted")
    return view.urgency_html(view.hours_left(rec.get("claim_deadline_at"), now))


def case_table(recs: list[dict], names: dict[str, str], claims: dict[str, dict], now: datetime) -> str:
    rows = []
    for r in recs:
        owed = r.get("diff", 0) > 0
        deadline = view.deadline_bar(r.get("claim_deadline_at"), now) if owed else '<span class="sa-subtle">—</span>'
        code = (f'{view.order_link(r["order_code"])}<div class="sa-subtle" style="font-size:12px;font-weight:400">'
                f'{esc(names.get(r["carrier"], r["carrier"]))}</div>')
        rows.append(([
            code,
            esc(view.DIFF_TYPE_LABELS.get(r["diff_type"], r["diff_type"])),
            view.num(r.get("expected_amount", 0)),
            view.num(r.get("actual_amount", 0)),
            view.money_cell(r.get("diff", 0)),
            deadline,
            level_cell(r, claims, now),
        ], ""))
    return view.table([("Mã đơn", False), ("Loại chênh lệch", False), ("Phải nhận", True), ("Thực nhận", True),
                       ("Lệch", True), ("Hạn khiếu nại", False), ("Mức", False)], rows, 680, compact=True)


def type_bars(recs: list[dict]) -> list[dict]:
    """Tổng chênh lệch theo loại, lớn trước: [{diff_type, label, count, amount}]."""
    agg: dict[str, dict] = {}
    for r in recs:
        a = agg.setdefault(r["diff_type"], {"diff_type": r["diff_type"], "count": 0, "amount": 0})
        a["count"] += 1
        a["amount"] += r.get("diff", 0)
    for a in agg.values():
        a["label"] = view.DIFF_TYPE_LABELS.get(a["diff_type"], a["diff_type"])
    return sorted(agg.values(), key=lambda a: (-abs(a["amount"]), a["diff_type"]))


def type_bars_html(recs: list[dict]) -> str:
    bars = type_bars(recs)
    scale = max((abs(b["amount"]) for b in bars), default=0) or 1
    out = []
    for b in bars:
        tone = "danger" if b["amount"] > 0 else ("warning" if b["amount"] < 0 else "muted")
        out.append(f'<div><div class="sa-split" style="margin-bottom:6px"><span>{esc(b["label"])}'
                   f'<span class="sa-subtle"> · {b["count"]} đơn</span></span>'
                   f'<span class="sa-mono sa-{view.money_tone(b["amount"])}" style="font-weight:600">'
                   f'{view.num(b["amount"], signed=True)}</span></div>{view.track(abs(b["amount"]) / scale * 100, tone)}</div>')
    return "".join(out) or '<div class="sa-muted">Không có chênh lệch nào.</div>'
