"""[B] Trang: So sánh hãng."""
from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from core import queries
from core.periods import period_bounds
from ui import shared, view

shared.header("So sánh hãng", "Thước đo chung, tính cùng một cách cho mọi hãng: số đơn có chênh lệch, tỉ lệ "
              "và số tiền chênh lệch. Dùng để so sánh các hãng, không xếp hạng hay đánh giá hãng.")
db = shared.db()
names = shared.carrier_names()
scale = shared.carrier_scale(names)

all_periods = queries.periods(db)
chosen = st.multiselect("Kỳ đối soát", all_periods, default=all_periods, key="cmp_periods",
                        format_func=view.period_label)
summary = queries.diff_summary(db, None, chosen or None)

rows = [{
    "Hãng": names.get(r["carrier"], r["carrier"]),
    "Số đơn đối soát": r["records"],
    "Số đơn có chênh lệch": r["diff_count"],
    "Tỉ lệ đơn có chênh lệch": r["diff_count"] / r["records"] if r["records"] else 0.0,
    "Tổng chênh lệch": r["diff_amount"],
    "Doanh nghiệp nhận thiếu": r["owed_amount"],
} for r in summary.get("by_carrier", [])]
if not rows:
    st.info("Chưa có dữ liệu đối soát cho các kỳ đã chọn.")
    st.stop()
st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
    "Tỉ lệ đơn có chênh lệch": st.column_config.NumberColumn(format="percent"),
    **shared.money_columns("Tổng chênh lệch", "Doanh nghiệp nhận thiếu"),
})

# ── Theo loại chênh lệch ──
st.subheader("Chênh lệch theo loại")
measure = st.radio("Đo theo", ["Số đơn", "Số tiền"], horizontal=True, key="cmp_measure")
by_type = pd.DataFrame([{
    "Hãng": names.get(r["carrier"], r["carrier"]),
    "Loại chênh lệch": view.DIFF_TYPE_LABELS.get(r["diff_type"], r["diff_type"]),
    "Số đơn": r["diff_count"],
    "Số tiền": r["diff_amount"],
    "Số tiền (₫)": view.vnd(r["diff_amount"]),
} for r in summary.get("by_type", [])])
if by_type.empty:
    st.success("Không có chênh lệch trong các kỳ đã chọn.")
else:
    type_order = [view.DIFF_TYPE_LABELS[d] for d in view.DIFF_TYPES]
    bars = alt.Chart(by_type).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("Loại chênh lệch:N", sort=type_order, title=None, axis=alt.Axis(labelAngle=0, labelLimit=220)),
        xOffset=alt.XOffset("Hãng:N", scale=alt.Scale(domain=scale.domain)),
        y=alt.Y(f"{measure}:Q", axis=shared.vnd_axis(f"{measure}{' (₫)' if measure == 'Số tiền' else ''}")),
        color=alt.Color("Hãng:N", scale=scale, legend=alt.Legend(orient="top", title=None)),
        tooltip=["Hãng", "Loại chênh lệch", "Số đơn", "Số tiền (₫)"],
    ).properties(height=320)
    st.altair_chart(bars, width="stretch")
    with st.expander("Bảng số liệu"):
        st.dataframe(by_type.drop(columns="Số tiền (₫)"), hide_index=True,
                     column_config=shared.money_columns("Số tiền"))

# ── Xu hướng theo ngày giao ──
st.subheader("Xu hướng chênh lệch theo ngày giao")
mode = st.radio("Cách cộng", ["7 ngày gần nhất", "Cộng dồn"], horizontal=True, key="cmp_trend")
since = until = None
if chosen:
    # Kỳ là kỳ chuyển tiền, ngày giao sớm hơn vài ngày: lấy rộng thêm một tuần về trước.
    since = period_bounds(min(chosen))[0] - timedelta(days=7)
    until = period_bounds(max(chosen))[1]
trend = queries.diff_trend_by_day(db, None, since, until)
if trend:
    field = "amount_7d" if mode == "7 ngày gần nhất" else "cumulative_amount"
    tdf = pd.DataFrame([{
        "Ngày": pd.Timestamp(t["day"]).tz_localize("UTC").tz_convert("Asia/Ho_Chi_Minh").tz_localize(None),
        "Hãng": names.get(t["carrier"], t["carrier"]),
        "Số tiền": t[field],
        "Số tiền (₫)": view.vnd(t[field]),
        "Số đơn": t["count_7d"] if field == "amount_7d" else t["cumulative_count"],
    } for t in trend])
    lines = alt.Chart(tdf).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=40)).encode(
        x=alt.X("Ngày:T", title=None, axis=alt.Axis(format="%d/%m")),
        y=alt.Y("Số tiền:Q", axis=shared.vnd_axis(f"Chênh lệch, {mode.lower()} (₫)")),
        color=alt.Color("Hãng:N", scale=scale, legend=alt.Legend(orient="top", title=None)),
        tooltip=[alt.Tooltip("Ngày:T", format="%d/%m/%Y"), "Hãng",
                 "Số tiền (₫)", "Số đơn"],
    ).properties(height=320)
    st.altair_chart(lines, width="stretch")
    with st.expander("Bảng số liệu"):
        st.dataframe(tdf.drop(columns="Số tiền (₫)"), hide_index=True, column_config={
            **shared.money_columns("Số tiền"), "Ngày": st.column_config.DateColumn(format="DD/MM/YYYY")})
