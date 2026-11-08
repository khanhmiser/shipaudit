"""[B] Trang: Tổng quan (theo bản thiết kế docs/design/Main.dc.html)."""
import streamlit as st

from core import queries
from ui import shared, view

db, now = shared.db(), shared.now()
names = shared.carrier_names()

head, tools = st.columns([4, 1], vertical_alignment="bottom")
period = tools.selectbox("Kỳ đối soát", [None, *reversed(queries.periods(db))], key="ov_period",
                         label_visibility="collapsed",
                         format_func=lambda p: "Tất cả các kỳ" if p is None else view.period_label(p))
summary = queries.diff_summary(db, None, [period] if period else None)
t = summary.get("totals") or {}
scope = view.period_label(period) if period else "Tất cả các kỳ"
shared.topbar("Tổng quan đối soát", f"{scope} · {len(names)} hãng · {t.get('records', 0):,} đơn đối soát".replace(",", "."),
              container=head)
if not t.get("records"):
    st.info("Chưa có dữ liệu đối soát. Chạy `make seed` hoặc nạp bảng kê.")
    st.stop()

# ── 4 thẻ KPI ──
soon = queries.expiring(db, now, within_hours=view.SOON_HOURS)["items"]
first = min((i["claim_deadline_at"] for i in soon), default=None)
c = st.columns(4)
c[0].html(view.kpi("Số tiền phải nhận", view.vnd(t["expected_amount"]), "Tính theo quy tắc từng hãng"))
c[1].html(view.kpi("Số tiền thực nhận", view.vnd(t["actual_amount"]), "Tiền hãng đã chuyển"))
c[2].html(view.kpi(
    "Chênh lệch", view.signed_vnd(t["diff_amount"]),
    f"{t['diff_count']:,} đơn có chênh lệch".replace(",", ".")
    + (f" · nhận thiếu {view.vnd(t['owed_amount'])}" if t["owed_amount"] != t["diff_amount"] else ""),
    tone=view.money_tone(t["diff_amount"]), alert=t["diff_amount"] > 0,
))
c[3].html(view.kpi(
    "Sắp hết hạn khiếu nại", f"{len(soon)} khoản",
    f"Sớm nhất còn {view.short_left(first, now)}" if first else f"Không có khoản nào trong {view.SOON_HOURS} giờ tới",
    tone="warning" if soon else "",
))

# ── Kết quả khiếu nại: đã gửi hãng, chờ phản hồi, đã thu hồi ──
outcomes = queries.claim_outcomes(db)


def _claims(*statuses: str, key: str = "count") -> int:
    return sum(o[key] for o in outcomes if o["status"] in statuses)


sent = _claims("SUBMITTED", "RECOVERED", "REJECTED")
if sent:
    waiting, recovered_n = _claims("SUBMITTED"), _claims("RECOVERED")
    recovered, claimed_back = _claims("RECOVERED", key="recovered"), _claims("RECOVERED", key="amount")
    k = st.columns(4)
    k[0].html(view.kpi("Đã khiếu nại hãng", view.vnd(_claims("SUBMITTED", "RECOVERED", "REJECTED", key="amount")),
                       f"{sent:,} claim đã gửi".replace(",", ".")))
    k[1].html(view.kpi("Chờ hãng phản hồi", view.vnd(_claims("SUBMITTED", key="amount")), f"{waiting:,} claim".replace(",", "."),
                       tone="warning" if waiting else ""))
    k[2].html(view.kpi("Đã thu hồi", view.vnd(recovered), f"{recovered_n:,} claim được hãng hoàn tiền".replace(",", ".")
                       + (f" · hãng hoàn thiếu {view.vnd(claimed_back - recovered)}" if claimed_back > recovered else ""),
                       tone="success" if recovered else ""))
    rejected = queries.list_claims(db, "REJECTED")
    planned = sum(1 for c in rejected if c.get("next_contact_at"))
    k[3].html(view.kpi("Bị từ chối, đang theo dõi", view.vnd(sum(int(c["amount"]) for c in rejected)),
                       f"{len(rejected)} claim · {planned} có hẹn liên hệ lại" if rejected else "Không có claim nào bị từ chối",
                       tone="danger" if rejected else ""))

# ── Chênh lệch theo hãng · Hạn khiếu nại ──
left, right = st.columns([3, 2])

by_carrier = {r["carrier"]: r for r in summary.get("by_carrier", [])}
top = max(by_carrier.values(), key=lambda r: r["diff_amount"], default=None)
scale = max((abs(r["diff_amount"]) for r in by_carrier.values()), default=0) or 1
bars = []
for code in sorted(names):
    amount = by_carrier.get(code, {}).get("diff_amount", 0)
    if amount:
        tone = "danger" if top and code == top["carrier"] else "warning"
        value = f'<span class="sa-mono sa-{tone}">{view.num(amount, signed=True)}</span>'
    else:
        tone, value = "primary", view.badge("Khớp", "success")
    bars.append(f'<div class="sa-bar-row"><div class="sa-name">{view.esc(names[code])}</div>'
                f'{view.track(abs(amount) / scale * 100, tone, height=14)}<div class="sa-val">{value}</div></div>')
if top and t["diff_amount"]:
    share = round(top["diff_amount"] / t["diff_amount"] * 100)
    types = [r for r in summary.get("by_type", []) if r["carrier"] == top["carrier"]]
    main_type = max(types, key=lambda r: r["diff_amount"], default=None)
    note = f"{names.get(top['carrier'], top['carrier'])} chiếm {share}% tổng chênh lệch ({scope.lower()})."
    if main_type:
        note += (f" Loại chênh lệch lớn nhất của hãng này: {view.DIFF_TYPE_LABELS[main_type['diff_type']].lower()}, "
                 f"{main_type['diff_count']} đơn, {view.vnd(main_type['diff_amount'])}.")
    bars.append(f'<div class="sa-note">{view.esc(note)}</div>')
left.html(view.card("Chênh lệch theo hãng", "".join(bars), f'<span class="sa-subtle" style="font-size:12px">'
                    f'{view.esc(scope)} · phải nhận − thực nhận</span>', body_style="display:flex;flex-direction:column;gap:18px"))

upcoming = queries.expiring(db, now, within_hours=view.HORIZON_HOURS)["items"][:5]
items = []
for i in upcoming:
    hours = view.hours_left(i["claim_deadline_at"], now)
    items.append(
        f'<div><div class="sa-split"><span>{view.order_link(i["order_code"])} <span class="sa-muted">· '
        f'{view.esc(names.get(i["carrier"], i["carrier"]))}</span></span><span class="{view.deadline_text_class(hours)}" '
        f'style="font-weight:600">{view.esc(view.short_left(i["claim_deadline_at"], now))}</span></div>'
        f'{view.track(hours / view.HORIZON_HOURS * 100, view.deadline_tone(hours))}</div>'
    )
if not items:
    items.append('<div class="sa-muted">Không có khoản nhận thiếu nào còn hạn khiếu nại trong 7 ngày tới.</div>')
right.html(view.card("Hạn khiếu nại", "".join(items), view.page_link("han-khieu-nai", "Xem tất cả"),
                     body_style="display:flex;flex-direction:column;gap:18px"))

# ── Đơn chênh lệch cần xử lý ──
recs = queries.list_reconciliations(db, None, period)
claim_of = queries.claim_by_reconciliation(db)
HANDLED = {"SUBMITTED": "accent", "RECOVERED": "success", "REJECTED": "danger"}  # claim đã gửi hãng: hết việc cần làm


def _handled(r: dict) -> str | None:
    status = (claim_of.get(r.get("reconciliation_id")) or {}).get("status")
    return status if status in HANDLED else None


def _priority(r: dict) -> tuple:
    hours = view.hours_left(r.get("claim_deadline_at"), now)
    claimable = r.get("diff", 0) > 0 and hours is not None and hours > 0 and not _handled(r)
    return (0, hours, -r["diff"]) if claimable else (1, 0, -abs(r.get("diff", 0)))


rows = []
for r in sorted(recs, key=_priority)[:8]:
    hours = view.hours_left(r.get("claim_deadline_at"), now)
    handled = _handled(r)
    rows.append(([
        view.order_link(r["order_code"]),
        view.esc(names.get(r["carrier"], r["carrier"])),
        view.esc(view.DIFF_TYPE_LABELS.get(r["diff_type"], r["diff_type"])),
        view.num(r.get("expected_amount", 0)),
        view.num(r.get("actual_amount", 0)),
        view.money_cell(r.get("diff", 0)),
        "—" if handled else f'<span class="{view.deadline_text_class(hours)}" style="font-weight:600">'
        f'{view.esc(view.short_left(r.get("claim_deadline_at"), now))}</span>',
        view.badge(view.CLAIM_STATUS_LABELS[handled], HANDLED[handled]) if handled else view.urgency_html(hours),
    ], ""))
table = view.table([("Mã đơn", False), ("Hãng", False), ("Loại chênh lệch", False), ("Phải nhận", True),
                    ("Thực nhận", True), ("Chênh lệch", True), ("Còn lại", False), ("Mức khẩn", False)], rows, 860)
st.html(f'<section class="sa-card"><div class="sa-card-h"><h2 class="sa-card-t">Đơn chênh lệch cần xử lý</h2>'
        f'{view.page_link("chenh-lech", f"Xem tất cả {len(recs):,} đơn →".replace(",", "."))}</div>{table}</section>')

with st.expander("Công thức đối soát"):
    st.write(view.FORMULA_TEXT)
st.html(view.footnote())
