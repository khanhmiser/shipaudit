"""[B] Phần thuần của giao diện (không gọi Streamlit): nhãn tiếng Việt, định dạng tiền và thời gian,
bảng breakdown từng khoản, các dòng bảng, CSS dùng chung và các hàm vẽ thành phần (thẻ KPI, badge,
thanh hạn khiếu nại...) trả về chuỗi HTML. Tách khỏi các trang để test được mà không cần chạy Streamlit.

CSS và thành phần theo bản thiết kế docs/design/ (bảng màu AML, dark mặc định). Mọi chuỗi lấy từ dữ liệu
đều đi qua html.escape trước khi ghép vào HTML.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta

from core.periods import VN_TZ, as_aware, period_bounds

# Màu phân loại theo thứ tự cố định, gán theo hãng (mã hãng xếp tăng dần), không theo thứ hạng.
SERIES_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")

DIFF_TYPE_LABELS = {
    "FEE_MISMATCH": "Cước lệch quy định",
    "RETURN_FEE_DOUBLE": "Phí hoàn lệch / trừ hai lần",
    "MISSING_IN_STATEMENT": "Thiếu trong bảng kê",
    "COD_MISMATCH": "Tiền thu hộ lệch",
    "LATE_PAYOUT": "Chuyển tiền chậm",
    "NONE": "Khớp",
}
DIFF_TYPES = tuple(k for k in DIFF_TYPE_LABELS if k != "NONE")
ORDER_STATUS_LABELS = {
    "DELIVERED": "Đã giao",
    "RETURNED": "Hoàn hàng",
    "RETURN_BY_CUSTOMER": "Trả hàng",
    "DEFECTIVE": "Hàng lỗi",
    "LOST": "Thất lạc",
}
CLAIM_STATUS_LABELS = {
    "DRAFT": "Nháp",
    "APPROVED": "Đã duyệt",
    "SUBMITTED": "Đã gửi hãng",
    "RECOVERED": "Đã thu hồi",
    "REJECTED": "Bị từ chối",
    "EXPIRED": "Quá hạn",
}
SOURCE_LABELS = {"manual": "Tạo tay", "datadog_webhook": "Cảnh báo Datadog"}
REGION_LABELS = {"noi_tinh": "Nội tỉnh", "noi_vung": "Nội vùng", "lien_vung": "Liên vùng"}

# Các khoản theo đúng thứ tự công thức đối soát: (trường, nhãn, dấu).
FORMULA_ITEMS = (
    ("cod_collected", "Tiền thu hộ", 1),
    ("prepaid_by_shop", "Doanh nghiệp trả trước", 1),
    ("return_fee_paid_by_shop", "Doanh nghiệp trả phí khi trả hàng", 1),
    ("shipping_fee", "Phí giao hàng", -1),
    ("insurance_fee", "Phí bảo hiểm", -1),
    ("return_shipping_fee", "Phí chuyển hoàn", -1),
    ("storage_fee", "Phí lưu kho", -1),
    ("address_change_fee", "Phí thay đổi địa chỉ", -1),
    ("inspection_fee", "Phí đồng kiểm", -1),
    ("promotion", "Khuyến mãi", 1),
    ("transfer_fee", "Phí chuyển khoản", -1),
)
FORMULA_TEXT = (
    "Tiền đối soát = tiền thu hộ + doanh nghiệp trả trước + doanh nghiệp trả phí khi trả hàng − phí giao hàng "
    "− phí bảo hiểm − phí chuyển hoàn − phí lưu kho − phí thay đổi địa chỉ − phí đồng kiểm + khuyến mãi "
    "− phí chuyển khoản. Chênh lệch = số tiền phải nhận − số tiền thực nhận; dương là doanh nghiệp nhận thiếu."
)
UNREPORTED = "Khoản hãng không ghi riêng"
TOTAL = "Tiền đối soát"


# ── Định dạng ──
def vnd(amount: int | None) -> str:
    """1234567 → "1.234.567 ₫". Tiền luôn là số nguyên VNĐ."""
    if amount is None:
        return "—"
    amount = int(amount)
    return f"{'−' if amount < 0 else ''}{abs(amount):,} ₫".replace(",", ".")


def signed_vnd(amount: int | None) -> str:
    if amount is None:
        return "—"
    return f"+{vnd(amount)}" if int(amount) > 0 else vnd(amount)


def dt_vn(value: datetime | str | None, seconds: bool = False) -> str:
    if value is None:
        return "—"
    return as_aware(value).astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M:%S" if seconds else "%d/%m/%Y %H:%M")


def hours_left(deadline: datetime | str | None, now: datetime) -> float | None:
    if deadline is None:
        return None
    return round((as_aware(deadline) - as_aware(now)).total_seconds() / 3600, 2)


def time_left(deadline: datetime | str | None, now: datetime) -> str:
    """Đồng hồ đếm ngược tới hạn khiếu nại: "Còn 2 ngày 5 giờ", "Còn 3 giờ 20 phút", "Quá hạn 1 ngày 2 giờ"."""
    if deadline is None:
        return "—"
    return _span((as_aware(deadline) - as_aware(now)).total_seconds())


def time_left_hours(hours: float | None) -> str:
    """Như time_left, nhưng nhận số giờ còn lại (pipeline trả về `hours_left`)."""
    return "—" if hours is None else _span(hours * 3600)


def _span(secs: float) -> str:
    minutes = int(abs(secs) // 60)
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    span = f"{days} ngày {hours} giờ" if days else f"{hours} giờ {mins} phút"
    return f"Còn {span}" if secs > 0 else f"Quá hạn {span}"


def period_label(period: str | None) -> str:
    """"2026-W42" → "Tuần 42/2026 (12/10–18/10)" (tuần ISO theo giờ Việt Nam)."""
    if not period:
        return "—"
    start, end = period_bounds(period)
    year, week = period.split("-W")
    return f"Tuần {int(week)}/{year} ({start:%d/%m}–{end - timedelta(days=1):%d/%m})"


def carrier_colors(names: dict[str, str]) -> tuple[list[str], list[str]]:
    """(tên hiển thị, màu) theo mã hãng tăng dần, để màu của một hãng không đổi khi lọc."""
    codes = sorted(names)
    return [names[c] for c in codes], [SERIES_COLORS[i % len(SERIES_COLORS)] for i in range(len(codes))]


# ── Breakdown từng khoản ──
def breakdown_rows(rec: dict, include_zero: bool = False) -> list[dict]:
    """Từng khoản cộng/trừ của một bản ghi đối soát: phải nhận (theo quy tắc hãng) so với thực nhận (theo bảng kê).

    Mỗi khoản ghi số dương, cột "Cộng/Trừ" cho biết chiều. Chênh lệch của từng khoản tính theo phần đóng góp
    vào tiền đối soát, (dấu × phải nhận) − (dấu × thực nhận), cùng chiều với chênh lệch của cả đơn.
    Khoản hãng không ghi riêng trong bảng kê thì để trống cột thực nhận; phần còn lại của số thực nhận
    (thực nhận − các khoản hãng có ghi) hiện ở dòng "Khoản hãng không ghi riêng". Dòng cuối là tổng.
    """
    expected = rec.get("breakdown") or {}
    actual = rec.get("actual_breakdown")  # None: đơn không có trong bảng kê
    actual_amount = int(rec.get("actual_amount", 0))
    rows: list[dict] = []
    for field, label, sign in FORMULA_ITEMS:
        exp = int(expected.get(field, 0))
        act = int(actual[field]) if actual and field in actual else None
        if not include_zero and exp == 0 and not act:
            continue
        rows.append({
            "Khoản": label, "Cộng/Trừ": "+" if sign > 0 else "−", "Phải nhận": exp, "Thực nhận": act,
            "Chênh lệch": None if act is None else sign * (exp - act),
        })
    if actual:
        known = sum(sign * int(actual[f]) for f, _, sign in FORMULA_ITEMS if f in actual)
        residual = actual_amount - known
        if residual:
            rows.append({"Khoản": UNREPORTED, "Cộng/Trừ": "+" if residual > 0 else "−", "Phải nhận": None,
                         "Thực nhận": abs(residual), "Chênh lệch": None})
    rows.append({"Khoản": TOTAL, "Cộng/Trừ": "=", "Phải nhận": int(rec.get("expected_amount", 0)),
                 "Thực nhận": actual_amount, "Chênh lệch": int(rec.get("diff", 0))})
    return rows


# ── Dòng bảng ──
def reconciliation_rows(recs: list[dict], names: dict[str, str], now: datetime) -> list[dict]:
    return [{
        "Mã đơn": r["order_code"],
        "Hãng": names.get(r["carrier"], r["carrier"]),
        "Kỳ": r.get("period") or "—",
        "Loại chênh lệch": DIFF_TYPE_LABELS.get(r["diff_type"], r["diff_type"]),
        "Trạng thái đơn": ORDER_STATUS_LABELS.get(r.get("order_status"), r.get("order_status") or "—"),
        "Phải nhận": int(r.get("expected_amount", 0)),
        "Thực nhận": int(r.get("actual_amount", 0)),
        "Chênh lệch": int(r.get("diff", 0)),
        "Hạn khiếu nại": dt_vn(r.get("claim_deadline_at")),
        "Còn lại": time_left(r.get("claim_deadline_at"), now),
        "Bảng kê": r["statement_id"],
    } for r in recs]


def expiring_rows(items: list[dict], names: dict[str, str], now: datetime) -> list[dict]:
    return [{
        "Mã đơn": i["order_code"],
        "Hãng": names.get(i["carrier"], i["carrier"]),
        "Loại chênh lệch": DIFF_TYPE_LABELS.get(i["diff_type"], i["diff_type"]),
        "Chênh lệch": int(i["diff"]),
        "Hạn khiếu nại": dt_vn(i["claim_deadline_at"]),
        "Còn lại": time_left(i["claim_deadline_at"], now),
        "Giờ còn lại": max(hours_left(i["claim_deadline_at"], now) or 0.0, 0.0),
        "Claim": CLAIM_STATUS_LABELS.get(i.get("claim_status"), "Chưa có"),
        "reconciliation_id": i["reconciliation_id"],
    } for i in items]


def claim_rows(claims: list[dict], names: dict[str, str], now: datetime) -> list[dict]:
    return [{
        "Mã claim": c["claim_id"],
        "Mã đơn": c["order_code"],
        "Hãng": names.get(c["carrier"], c["carrier"]),
        "Loại chênh lệch": DIFF_TYPE_LABELS.get(c["diff_type"], c["diff_type"]),
        "Số tiền": int(c["amount"]),
        "Trạng thái": CLAIM_STATUS_LABELS.get(c["status"], c["status"]),
        "Nguồn": SOURCE_LABELS.get(c.get("source"), c.get("source") or "—"),
        "Tạo lúc": dt_vn(c.get("created_at")),
        "Hạn khiếu nại": dt_vn(c.get("claim_deadline_at")),
        "Còn lại": time_left(c.get("claim_deadline_at"), now) if c["status"] in ("DRAFT", "APPROVED") else "—",
    } for c in claims]


# ── Giao diện: CSS dùng chung (bảng màu AML, docs/design/aml-ui.css) ──
SOON_HOURS = 72  # "sắp hết hạn khiếu nại": còn dưới 72 giờ
HORIZON_HOURS = 168  # thanh hạn khiếu nại đầy khi còn từ 7 ngày trở lên

CSS = """
<style>
:root {
  --sa-bg: #0b1117; --sa-bg-sunken: #070d10; --sa-surface: #11171e; --sa-surface-2: #131b23; --sa-surface-3: #1b2a31;
  --sa-border: #1b2f35; --sa-border-strong: #234149; --sa-divider: #162026;
  --sa-text: #e6edf1; --sa-text-muted: #9db3bd; --sa-text-subtle: #6b8590; --sa-text-on-accent: #04100d;
  --sa-primary: #10b090; --sa-primary-soft: rgba(16,176,144,.14); --sa-primary-fg: #10b090;
  --sa-accent-soft: rgba(139,124,246,.16); --sa-accent-fg: #a193fb; --sa-link: #6aa2f5;
  --sa-success: #30b070; --sa-success-soft: rgba(48,176,112,.15); --sa-success-fg: #4acd80;
  --sa-warning: #e9a21a; --sa-warning-soft: rgba(233,162,26,.15); --sa-warning-fg: #e9a21a;
  --sa-danger: #d94848; --sa-danger-soft: rgba(217,72,72,.16); --sa-danger-fg: #f26b6b;
  --sa-info: #4080e0; --sa-info-soft: rgba(64,128,224,.16); --sa-info-fg: #6aa2f5;
  --sa-risk-critical: #ef4444; --sa-risk-high: #f27a1a; --sa-risk-medium: #e9a21a; --sa-risk-low: #30b070;
  --sa-risk-none: #586f79;
  --sa-shadow-sm: 0 1px 2px rgba(0,0,0,.45);
  --sa-grad-brand: linear-gradient(135deg, #10b090, #4080e0);
  --sa-mono: "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace;
}
/* Khung Streamlit */
[data-testid="stMainBlockContainer"] { padding-top: 4.5rem; padding-bottom: 3.5rem; }
[data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"] { font-size: 11px; font-weight: 600;
  letter-spacing: .08em; text-transform: uppercase; color: var(--sa-text-subtle); }
[data-testid="stSidebarNav"] a { border-radius: 8px; min-height: 40px; }
[data-testid="stSidebarNav"] a[aria-current="page"] { background: var(--sa-primary-soft); }
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: var(--sa-primary-fg); font-weight: 600; }

/* Thành phần */
.sa-mono { font-family: var(--sa-mono); font-variant-numeric: tabular-nums; }
.sa-muted { color: var(--sa-text-muted); } .sa-subtle { color: var(--sa-text-subtle); }
.sa-danger { color: var(--sa-danger-fg); } .sa-warning { color: var(--sa-warning-fg); }
.sa-success { color: var(--sa-success-fg); } .sa-primary { color: var(--sa-primary-fg); }
.sa-brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 16px; color: var(--sa-text);
  padding: 2px 4px 6px; }
.sa-brand i { width: 26px; height: 26px; border-radius: 8px; background: var(--sa-grad-brand); display: inline-block; }
.sa-topbar { display: flex; flex-wrap: wrap; gap: 12px 16px; align-items: flex-end; justify-content: space-between;
  margin-bottom: 4px; }
.sa-crumb { font-size: 13px; color: var(--sa-text-muted); margin-bottom: 6px; }
.sa-crumb a, .sa-link { color: var(--sa-link); text-decoration: none; }
.sa-crumb a:hover, .sa-link:hover { text-decoration: underline; }
.sa-h1 { font-size: 26px; font-weight: 700; letter-spacing: -.01em; margin: 0; line-height: 1.25; color: var(--sa-text); }
.sa-sub { color: var(--sa-text-muted); font-size: 13px; margin-top: 4px; }
.sa-title-row { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.sa-card { background: var(--sa-surface); border: 1px solid var(--sa-border); border-radius: 12px;
  box-shadow: var(--sa-shadow-sm); min-width: 0; color: var(--sa-text); font-size: 14px; line-height: 1.5; }
.sa-card.sa-alert { border-color: var(--sa-danger); }
.sa-card-h { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 20px 0; }
.sa-card-t { font-size: 14px; font-weight: 600; margin: 0; padding: 0; color: var(--sa-text); }
.sa-card-b { padding: 16px 20px 20px; }
.sa-kpi { padding: 18px 20px; }
.sa-kpi-l { font-size: 12px; color: var(--sa-text-subtle); font-weight: 600; letter-spacing: .05em; text-transform: uppercase; }
.sa-kpi-v { font-size: clamp(16px, 1.3vw, 26px); font-weight: 700; margin-top: 8px; letter-spacing: -.02em;
  font-family: var(--sa-mono); font-variant-numeric: tabular-nums; white-space: nowrap; line-height: 1.25; }
.sa-kpi-s { font-size: 12px; color: var(--sa-text-muted); margin-top: 4px; }
.sa-badge { display: inline-flex; align-items: center; padding: 2px 10px; border-radius: 999px; font-size: 12px;
  font-weight: 600; white-space: nowrap; }
.sa-b-success { background: var(--sa-success-soft); color: var(--sa-success-fg); }
.sa-b-warning { background: var(--sa-warning-soft); color: var(--sa-warning-fg); }
.sa-b-danger { background: var(--sa-danger-soft); color: var(--sa-danger-fg); }
.sa-b-info { background: var(--sa-info-soft); color: var(--sa-info-fg); }
.sa-b-accent { background: var(--sa-accent-soft); color: var(--sa-accent-fg); }
.sa-b-muted { background: var(--sa-surface-3); color: var(--sa-text-muted); }
.sa-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: 0 0 8px; }
.sa-risk { display: inline-flex; align-items: center; gap: 8px; font-weight: 600; white-space: nowrap; }
.sa-track { height: 8px; border-radius: 4px; background: var(--sa-surface-3); overflow: hidden; }
.sa-fill { height: 100%; border-radius: 4px; }
.sa-f-danger { background: var(--sa-danger); } .sa-f-warning { background: var(--sa-warning); }
.sa-f-primary { background: var(--sa-primary); } .sa-f-info { background: var(--sa-info); }
.sa-f-muted { background: var(--sa-risk-none); }
.sa-note { background: var(--sa-info-soft); border-radius: 8px; padding: 12px 14px; font-size: 13px; color: var(--sa-text); }
.sa-note.sa-bad { background: var(--sa-danger-soft); } .sa-note.sa-warn { background: var(--sa-warning-soft); }
.sa-stack { display: flex; flex-direction: column; gap: 18px; }
.sa-bar-row { display: flex; align-items: center; gap: 14px; }
.sa-bar-row .sa-name { flex: 0 0 96px; font-weight: 500; }
.sa-bar-row .sa-track { flex: 1 1 auto; height: 14px; }
.sa-bar-row .sa-val { flex: 0 0 120px; text-align: right; font-weight: 600; }
.sa-split { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.sa-scroll { overflow-x: auto; padding-top: 8px; }
.sa-tbl { width: 100%; border-collapse: collapse; color: var(--sa-text); font-size: 14px; margin: 0; }
.sa-tbl th { color: var(--sa-text-subtle); text-align: left; font-size: 12px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .05em; padding: 10px 16px; border: 0; border-bottom: 1px solid var(--sa-border); white-space: nowrap;
  background: transparent; }
.sa-tbl td, .sa-tbl tbody th { padding: 13px 16px; border: 0; border-bottom: 1px solid var(--sa-divider); text-align: left;
  font-weight: 400; vertical-align: middle; text-transform: none; letter-spacing: 0; font-size: 14px; color: var(--sa-text);
  white-space: normal; }
.sa-tbl .num, .sa-tbl thead .num { text-align: right; }
.sa-tbl.sa-compact th, .sa-tbl.sa-compact td, .sa-tbl.sa-compact tbody th { padding-left: 10px; padding-right: 10px; }
.sa-tbl tbody tr:hover td, .sa-tbl tbody tr:hover th { background: var(--sa-surface-2); }
.sa-tbl tbody tr:last-child td, .sa-tbl tbody tr:last-child th { border-bottom: 0; }
.sa-tbl tr.sa-hl td, .sa-tbl tr.sa-hl th { background: var(--sa-danger-soft); }
.sa-tbl tr.sa-total td, .sa-tbl tr.sa-total th { font-weight: 700; border-top: 1px solid var(--sa-border); }
.sa-foot { color: var(--sa-text-subtle); font-size: 12px; margin: 20px 0 0; }
.sa-tl { list-style: none; margin: 0; padding: 0; }
.sa-tl li { display: flex; gap: 12px; position: relative; padding-bottom: 18px; }
.sa-tl li:last-child { padding-bottom: 0; }
.sa-tl li:not(:last-child)::before { content: ""; position: absolute; left: 5px; top: 18px; bottom: 0; width: 2px;
  background: var(--sa-border); }
.sa-pin { flex: 0 0 12px; width: 12px; height: 12px; border-radius: 50%; margin-top: 5px; background: var(--sa-primary); }
.sa-pin.now { background: transparent; border: 2px solid var(--sa-primary); }
.sa-pin.wait { background: var(--sa-surface-3); border: 2px solid var(--sa-border-strong); }
.sa-pin.warn { background: var(--sa-warning); }
.sa-pair { display: flex; flex-wrap: wrap; gap: 12px; }
.sa-pair > div { flex: 1 1 220px; border-radius: 8px; padding: 12px 14px; background: var(--sa-surface-3); }
.sa-pair > div.bad { background: var(--sa-danger-soft); }
.sa-pair .sa-kpi-l { margin-bottom: 6px; }
.sa-big { font-size: 26px; font-weight: 700; font-family: var(--sa-mono); font-variant-numeric: tabular-nums; }
.sa-chips { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
</style>
"""

TONES = ("success", "warning", "danger", "info", "accent", "muted")


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def num(amount: int | None, signed: bool = False) -> str:
    """Số tiền cho bảng (không kèm ₫): 1234567 → "1.234.567"; signed thêm dấu + cho số dương."""
    if amount is None:
        return "—"
    s = vnd(amount)[:-2]
    return f"+{s}" if signed and int(amount) > 0 else s


def money_tone(amount: int | None) -> str:
    """Chênh lệch dương (doanh nghiệp nhận thiếu) đỏ, âm (nhận thừa) vàng, bằng 0 mờ."""
    if not amount:
        return "subtle"
    return "danger" if amount > 0 else "warning"


def money_cell(amount: int | None, signed: bool = True, bold: bool = True) -> str:
    weight = ' style="font-weight:600"' if bold and amount else ""
    return f'<span class="sa-{money_tone(amount)}"{weight}>{num(amount, signed)}</span>'


def badge(text: str, tone: str = "muted") -> str:
    return f'<span class="sa-badge sa-b-{tone if tone in TONES else "muted"}">{esc(text)}</span>'


def synthetic_badge() -> str:
    return badge("DỮ LIỆU TỔNG HỢP", "accent")


def urgency(hours: float | None) -> tuple[str, str]:
    """Mức khẩn của một khoản theo thời gian còn lại để khiếu nại: (nhãn, màu CSS).
    Chỉ dựa vào hạn khiếu nại, không đánh giá hãng."""
    if hours is None or hours <= 0:
        return "Quá hạn", "var(--sa-risk-none)"
    if hours < 24:
        return "Nghiêm trọng", "var(--sa-risk-critical)"
    if hours < 48:
        return "Cao", "var(--sa-risk-high)"
    if hours < 96:
        return "Trung bình", "var(--sa-risk-medium)"
    return "Thấp", "var(--sa-risk-low)"


def urgency_html(hours: float | None) -> str:
    label, color = urgency(hours)
    return (f'<span class="sa-risk"><span class="sa-dot" style="background:{color}"></span>'
            f'<span style="color:{color}">{label}</span></span>')


def deadline_tone(hours: float | None) -> str:
    if hours is None or hours <= 0:
        return "muted"
    if hours < 24:
        return "danger"
    if hours < 48:
        return "warning"
    return "primary"


def track(pct: float, tone: str = "primary", height: int | None = None) -> str:
    pct = max(0.0, min(float(pct), 100.0))
    style = f' style="height:{height}px"' if height else ""
    fill = f'<div class="sa-fill sa-f-{tone}" style="width:{pct:.0f}%"></div>' if pct > 0 else ""
    return f'<div class="sa-track"{style}>{fill}</div>'


def short_left(deadline, now: datetime) -> str:
    """Thời gian còn lại dạng ngắn cho bảng: "18 giờ", "1 ngày 6 giờ", "Quá hạn"."""
    hours = hours_left(deadline, now)
    if hours is None:
        return "—"
    if hours <= 0:
        return "Quá hạn"
    days, rest = divmod(int(hours), 24)
    if days and rest:
        return f"{days} ngày {rest} giờ"
    if days:
        return f"{days} ngày"
    return f"{rest} giờ" if rest else f"{int(hours * 60)} phút"


def deadline_text_class(hours: float | None) -> str:
    return {"danger": "sa-danger", "warning": "sa-warning", "muted": "sa-subtle"}.get(deadline_tone(hours), "")


def deadline_bar(deadline, now: datetime) -> str:
    """Ô hạn khiếu nại: thời gian còn lại (màu theo mức khẩn) và thanh đếm ngược (đầy khi còn từ 7 ngày)."""
    hours = hours_left(deadline, now)
    pct = 0 if not hours or hours <= 0 else hours / HORIZON_HOURS * 100
    return (f'<div class="{deadline_text_class(hours)}" style="font-weight:600;margin-bottom:6px;white-space:nowrap">'
            f'{esc(short_left(deadline, now))}</div>{track(pct, deadline_tone(hours))}')


def kpi(label: str, value: str, sub: str = "", tone: str = "", alert: bool = False) -> str:
    v_cls = f" sa-{tone}" if tone else ""
    alert_cls = " sa-alert" if alert else ""
    return (f'<div class="sa-card sa-kpi{alert_cls}"><div class="sa-kpi-l">{esc(label)}</div>'
            f'<div class="sa-kpi-v{v_cls}">{esc(value).replace(" ₫", "&nbsp;₫")}</div>'
            f'<div class="sa-kpi-s">{esc(sub)}</div></div>')


def card(title: str, body: str, right: str = "", alert: bool = False, body_style: str = "") -> str:
    """Thẻ có tiêu đề. `body` và `right` là HTML đã escape."""
    style = f' style="{body_style}"' if body_style else ""
    alert_cls = " sa-alert" if alert else ""
    return (f'<section class="sa-card{alert_cls}"><div class="sa-card-h"><h2 class="sa-card-t">{esc(title)}</h2>'
            f'{right}</div><div class="sa-card-b"{style}>{body}</div></section>')


def table(headers: list[tuple[str, bool]], rows: list[tuple[list[str], str]], min_width: int = 720,
          compact: bool = False) -> str:
    """Bảng HTML. headers: (nhãn, là cột số). rows: (các ô HTML đã escape, class của dòng). Ô đầu là tiêu đề dòng.
    compact: ô hẹp hơn, cho bảng nhiều cột đặt cạnh cột phụ."""
    num_cls = ' class="num"'
    head = "".join(f'<th scope="col"{num_cls if is_num else ""}>{esc(h)}</th>' for h, is_num in headers)
    body = []
    for cells, row_cls in rows:
        tds = []
        for i, (cell, (_, is_num)) in enumerate(zip(cells, headers)):
            tag = "th" if i == 0 else "td"
            attrs = (' scope="row"' if i == 0 else "") + (' class="num sa-mono"' if is_num else "")
            tds.append(f"<{tag}{attrs}>{cell}</{tag}>")
        tr_cls = f' class="{row_cls}"' if row_cls else ""
        body.append(f"<tr{tr_cls}>{''.join(tds)}</tr>")
    tbl_cls = "sa-tbl sa-compact" if compact else "sa-tbl"
    return (f'<div class="sa-scroll"><table class="{tbl_cls}" style="min-width:{min_width}px"><thead><tr>{head}</tr>'
            f'</thead><tbody>{"".join(body)}</tbody></table></div>')


def page_link(page: str, text: str, mono: bool = False, **params) -> str:
    """Liên kết sang trang khác của app, mở trong cùng tab. page là url_path khai báo trong ui/app.py."""
    query = "&".join(f"{k}={esc(v)}" for k, v in params.items())
    href = f"{page}?{query}" if query else page
    cls = "sa-link sa-mono" if mono else "sa-link"
    return f'<a class="{cls}" href="{href}" target="_self">{esc(text)}</a>'


def order_link(code: str) -> str:
    return page_link("chi-tiet-don", code, mono=True, order=code)


def topbar(title: str, sub: str = "", crumb: str = "", tools: str = "", title_extra: str = "",
           mono: bool = False) -> str:
    """Đầu trang: breadcrumb, tiêu đề (kèm badge), dòng phụ, và cụm công cụ bên phải (mặc định badge dữ liệu tổng hợp)."""
    crumb_html = f'<div class="sa-crumb">{crumb}</div>' if crumb else ""
    mono_cls = " sa-mono" if mono else ""
    h1 = f'<h1 class="sa-h1{mono_cls}">{esc(title)}</h1>'
    head = f'<div class="sa-title-row">{h1}{title_extra}</div>' if title_extra else h1
    sub_html = f'<div class="sa-sub">{esc(sub)}</div>' if sub else ""
    return (f'<div class="sa-topbar"><div>{crumb_html}{head}{sub_html}</div>'
            f'<div class="sa-title-row">{tools or synthetic_badge()}</div></div>')


def footnote(text: str = "Dữ liệu tổng hợp, hãng giả định (Carrier A/B/C). Không dùng dữ liệu thật của doanh nghiệp.") -> str:
    return f'<p class="sa-foot">{esc(text)}</p>'
