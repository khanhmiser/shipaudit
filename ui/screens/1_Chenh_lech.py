"""[B] Trang: Danh sách chênh lệch (theo bản thiết kế docs/design/Cases.dc.html)."""
import math

import pandas as pd
import streamlit as st

from core import queries
from ui import cases, shared, view

PAGE_SIZE = 25

db, now = shared.db(), shared.now()
names = shared.carrier_names()
claims = queries.claim_by_reconciliation(db)
head, tools = st.columns([4, 1], vertical_alignment="bottom")  # đầu trang, điền sau khi biết số liệu

# ── Bộ lọc (khai báo trước để tính số đếm của tab; đặt vào cột theo bố cục thiết kế) ──
f = st.columns([2, 2, 3, 3], vertical_alignment="bottom")
query = f[0].text_input("Tìm mã đơn", key="diff_q", placeholder="Tìm mã đơn...")
carrier = shared.carrier_select(names, "diff_carrier", f[1])
diff_type = f[2].selectbox("Loại chênh lệch", [None, *view.DIFF_TYPES], key="diff_type",
                           format_func=lambda d: "Tất cả các loại" if d is None else view.DIFF_TYPE_LABELS[d])
period = f[3].selectbox("Kỳ đối soát", [None, *reversed(queries.periods(db))], key="diff_period",
                        format_func=lambda p: "Tất cả các kỳ" if p is None else view.period_label(p))

base = [r for r in queries.list_reconciliations(db, carrier, period, diff_type, limit=5_000)
        if cases.matches_query(r, query)]
counts = cases.tab_counts(base, claims, now)
tab = st.segmented_control(
    "Trạng thái", [t for t, _ in cases.TABS], default="all", key="diff_tab", label_visibility="collapsed",
    format_func=lambda t: f"{dict(cases.TABS)[t]} ({counts[t]})",
) or "all"
shown = sorted((r for r in base if cases.in_tab(r, tab, claims, now)), key=lambda r: cases.priority(r, now))

total = sum(r.get("diff", 0) for r in shown)
scope = view.period_label(period) if period else "Tất cả các kỳ"
shared.topbar("Danh sách chênh lệch", f"{len(shown):,} đơn · tổng {view.signed_vnd(total)} · {scope}".replace(",", "."),
              crumb="Đối soát / Chênh lệch", container=head)
if shown:
    csv = pd.DataFrame(view.reconciliation_rows(shown, names, now)).to_csv(index=False).encode("utf-8-sig")
    if tools.download_button("Xuất CSV", csv, "chenh-lech.csv", "text/csv", key="export_csv"):
        shared.track("export_csv", rows=len(shown))

left, right = st.columns([3, 1])
with left:
    if not shown:
        st.success("Không có chênh lệch nào với bộ lọc này.")
    else:
        pages = max(1, math.ceil(len(shown) / PAGE_SIZE))
        sig = f"{carrier}|{period}|{diff_type}|{tab}|{query}"
        page = 1
        if pages > 1:
            page = int(st.columns([1, 4])[0].number_input(f"Trang (1–{pages})", 1, pages, 1, key=f"diff_page_{sig}"))
        part = shown[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        st.html(f'<section class="sa-card">{cases.case_table(part, names, claims, now)}</section>')
        st.caption(f"Hiển thị {(page - 1) * PAGE_SIZE + 1}–{(page - 1) * PAGE_SIZE + len(part)} / {len(shown)} đơn. "
                   "Chênh lệch = phải nhận − thực nhận; dương là doanh nghiệp nhận thiếu. Bấm mã đơn để xem bằng chứng.")
with right:
    st.html(view.card("Theo loại chênh lệch", cases.type_bars_html(shown), body_style="display:flex;flex-direction:column;gap:14px"))
    soon48 = sum(1 for r in shown if cases.is_claimable(r, now) and view.hours_left(r["claim_deadline_at"], now) < 48)
    if soon48:
        st.html(f'<div class="sa-note sa-warn" style="margin-top:16px">{soon48} đơn còn dưới 48 giờ để khiếu nại. '
                "Mở đơn để xem bằng chứng và soạn khiếu nại.</div>")

with st.expander("Đối chiếu đơn thiếu trong bảng kê"):
    st.caption("Đơn đã giao thuộc bảng kê của kỳ nhưng không có dòng nào trong bảng kê đó. "
               "Nếu đơn có ở bảng kê kỳ khác thì là chuyển chậm.")
    if not carrier or not period:
        st.info("Chọn một hãng và một kỳ đối soát ở bộ lọc phía trên.")
    else:
        missing = queries.missing_in_statement(db, carrier, period)
        if not missing:
            st.success("Bảng kê có đủ mọi đơn của kỳ.")
        else:
            st.dataframe(pd.DataFrame([{
                "Mã đơn": m["order_code"],
                "Trạng thái đơn": view.ORDER_STATUS_LABELS.get(m["status"], m["status"]),
                "Thu hộ": int(m["cod_amount"]),
                "Ngày giao": view.dt_vn(m["delivered_at"]),
                "Tình trạng": "Có ở bảng kê kỳ khác (chuyển chậm)" if m["late"] else "Chưa có ở bảng kê nào",
                "Bảng kê khác": ", ".join(m["other_statements"]) or "—",
            } for m in missing]), hide_index=True, column_config=shared.money_columns("Thu hộ"))
            st.caption(f"{len(missing)} đơn thiếu trong bảng kê {view.period_label(period)} của {names[carrier]}.")
st.html(view.footnote())
