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

# ── Chênh lệch theo thời gian ──
st.subheader("Chênh lệch theo thời gian")
st.caption("Tính theo ngày giao hàng của đơn. Chênh lệch = số tiền phải nhận − số tiền thực nhận "
           "(số âm là doanh nghiệp nhận thừa).")
MODES = {
    "Từng tuần": "Mỗi cột là tổng chênh lệch của các đơn giao trong tuần đó (thứ Hai đến Chủ nhật), "
                 "cùng cách chia kỳ đối soát. Cột cao là tuần có nhiều chênh lệch.",
    "Từng ngày": "Mỗi điểm là tổng chênh lệch của các đơn giao đúng ngày đó.",
    "Cộng dồn từ đầu": "Mỗi điểm là tổng chênh lệch từ ngày đầu tiên tới ngày đó. Đường càng dốc là chênh lệch "
                       "phát sinh càng nhanh; đường đi ngang là không phát sinh thêm.",
}
f = st.columns([3, 3, 2])
mode = f[0].radio("Xem theo", list(MODES), horizontal=True, key="cmp_trend_mode")
picked = f[1].multiselect("Hãng", sorted(names), default=sorted(names), key="cmp_trend_carriers",
                          format_func=lambda c: names[c])
measure_t = f[2].radio("Đo theo", ["Số tiền", "Số đơn"], horizontal=True, key="cmp_trend_measure")
st.caption(MODES[mode])

since = until = None
if chosen:
    # Kỳ là kỳ chuyển tiền, ngày giao sớm hơn vài ngày: lấy rộng thêm một tuần về trước.
    since = period_bounds(min(chosen))[0] - timedelta(days=7)
    until = period_bounds(max(chosen))[1]
weekly = mode == "Từng tuần"
trend = [t for t in queries.diff_trend_by_day(db, None, since, until, unit="week" if weekly else "day")
         if t["carrier"] in picked]
if not picked:
    st.info("Chọn ít nhất một hãng.")
elif not trend:
    st.info("Không có chênh lệch trong khoảng thời gian đã chọn.")
else:
    cumulative = mode == "Cộng dồn từ đầu"
    rows = []
    for t in trend:
        day = pd.Timestamp(t["day"]).tz_localize("UTC").tz_convert("Asia/Ho_Chi_Minh").tz_localize(None)
        amount = t["cumulative_amount"] if cumulative else t["diff_amount"]
        count = t["cumulative_count"] if cumulative else t["diff_count"]
        iso = day.isocalendar()
        rows.append({
            "Ngày": day,
            "Tuần": view.period_label(f"{iso[0]}-W{iso[1]:02d}"),
            "Hãng": names.get(t["carrier"], t["carrier"]),
            "Số tiền": amount,
            "Số tiền (₫)": view.vnd(amount),
            "Số đơn": count,
        })
    tdf = pd.DataFrame(rows)
    y_title = "Chênh lệch (₫)" if measure_t == "Số tiền" else "Số đơn có chênh lệch"
    y_axis = shared.vnd_axis(y_title) if measure_t == "Số tiền" else alt.Axis(title=y_title, format="d")
    color = alt.Color("Hãng:N", scale=scale, legend=alt.Legend(orient="top", title=None))
    if weekly:
        week_order = list(dict.fromkeys(tdf.sort_values("Ngày")["Tuần"]))
        chart = alt.Chart(tdf).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("Tuần:N", sort=week_order, title=None, axis=alt.Axis(labelAngle=0, labelLimit=180)),
            xOffset=alt.XOffset("Hãng:N", scale=alt.Scale(domain=scale.domain)),
            y=alt.Y(f"{measure_t}:Q", axis=y_axis),
            color=color,
            tooltip=["Tuần", "Hãng", "Số tiền (₫)", "Số đơn"],
        )
    else:
        chart = alt.Chart(tdf).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=40)).encode(
            x=alt.X("Ngày:T", title=None, axis=alt.Axis(format="%d/%m")),
            y=alt.Y(f"{measure_t}:Q", axis=y_axis),
            color=color,
            tooltip=[alt.Tooltip("Ngày:T", format="%d/%m/%Y"), "Hãng", "Số tiền (₫)", "Số đơn"],
        )
    st.altair_chart(chart.properties(height=320), width="stretch")
    with st.expander("Bảng số liệu"):
        cols = ["Tuần", "Hãng", "Số tiền", "Số đơn"] if weekly else ["Ngày", "Hãng", "Số tiền", "Số đơn"]
        st.dataframe(tdf[cols], hide_index=True, column_config={
            **shared.money_columns("Số tiền"), "Ngày": st.column_config.DateColumn(format="DD/MM/YYYY")})
