"""[B] Trang: Hạn khiếu nại (đồng hồ đếm ngược)."""
import pandas as pd
import streamlit as st

from core import queries
from core.claims import ClaimError
from ui import shared, view

WINDOWS = {24: "24 giờ tới", 48: "2 ngày tới", 72: "3 ngày tới", 168: "7 ngày tới"}

shared.header("Hạn khiếu nại", "Chênh lệch doanh nghiệp nhận thiếu, còn hạn khiếu nại và chưa gửi claim, "
              "gần hạn trước. Đồng hồ tự cập nhật mỗi phút.")
db = shared.db()
names = shared.carrier_names()

SORTS = {"soon": "Gần hạn trước (mặc định)", "late": "Hạn xa nhất trước", "diff": "Chênh lệch lớn nhất trước",
         "az": "Mã đơn A → Z", "za": "Mã đơn Z → A"}
SORT_KEYS = {
    "soon": lambda i: (view.as_aware(i["claim_deadline_at"]).timestamp(), i["order_code"]),
    "late": lambda i: (-view.as_aware(i["claim_deadline_at"]).timestamp(), i["order_code"]),
    "diff": lambda i: (-i["diff"], i["order_code"]),
    "az": lambda i: i["order_code"].lower(),
    "za": lambda i: i["order_code"].lower(),
}

f = st.columns(3)
carrier = shared.carrier_select(names, "exp_carrier", f[0])
window = f[1].selectbox("Hết hạn trong", list(WINDOWS), index=2, key="exp_window", format_func=WINDOWS.get)
sort = f[2].selectbox("Sắp xếp theo", list(SORTS), key="exp_sort", format_func=SORTS.get)


def _create(reconciliation_ids: list[str]) -> None:
    svc, made, errors = shared.claim_service(), [], []
    for rid in reconciliation_ids:
        try:
            made.append(svc.create_draft(rid, "manual"))
        except ClaimError as e:
            errors.append(str(e))
    shared.track("claim_draft_bulk", count=len(made), errors=len(errors), amount=sum(c["amount"] for c in made),
                 carrier=",".join(sorted({c["carrier"] for c in made})))
    shared.claim_event("created", made, source="manual")
    msg = f"Đã có {len(made)} claim nháp, chờ người duyệt ở trang Claims."
    shared.flash(msg + (f" {len(errors)} đơn không tạo được: {errors[0]}" if errors else ""))
    st.rerun()


@st.fragment(run_every="60s")
def board() -> None:
    now = shared.now()
    data = queries.expiring(db, now, within_hours=window, carrier=carrier)
    st.caption(f"Cập nhật lúc {view.dt_vn(now, seconds=True)}")
    if not data["items"]:
        st.success(f"Không có chênh lệch nào hết hạn khiếu nại trong {WINDOWS[window]}.")
        return

    cols = st.columns(max(len(data["by_carrier"]), 1))
    for col, row in zip(cols, data["by_carrier"]):
        with col.container(border=True):
            name = names.get(row["carrier"], row["carrier"])
            st.markdown(f"**{name}**")
            st.metric("Số tiền sắp hết hạn", view.vnd(row["amount"]), help=f"{row['count']} đơn")
            st.caption(f"{row['count']} đơn · đơn gần hạn nhất: {view.time_left_hours(row['min_hours_left'])} · "
                       f"{row['without_claim']} đơn chưa có claim")

    items = sorted(data["items"], key=SORT_KEYS[sort], reverse=(sort == "za"))
    df = pd.DataFrame(view.expiring_rows(items, names, now))
    event = st.dataframe(
        df, hide_index=True, key="exp_table", on_select="rerun", selection_mode="multi-row",
        column_order=[c for c in df.columns if c != "reconciliation_id"],
        column_config={
            **shared.money_columns("Chênh lệch"),
            "Giờ còn lại": st.column_config.ProgressColumn("Thời gian còn lại", min_value=0, max_value=window,
                                                           format="%.0f giờ"),
        },
    )
    chosen = [df.iloc[i]["reconciliation_id"] for i in event.selection.rows]
    without = df.loc[df["Claim"] == "Chưa có", "reconciliation_id"].tolist()
    if shared.read_only():
        st.caption(shared.READ_ONLY_NOTE)
        return
    b = st.columns(2)
    if b[0].button(f"Tạo claim nháp cho {len(chosen)} đơn đã chọn", disabled=not chosen, key="draft_chosen"):
        _create(chosen)
    if b[1].button(f"Tạo claim nháp cho mọi đơn chưa có claim ({len(without)})", disabled=not without,
                   key="draft_all"):
        _create(without)
    st.caption("Claim nháp chưa được gửi đi. Người duyệt kiểm tra và duyệt ở trang Claims trước khi gửi hãng.")


board()
