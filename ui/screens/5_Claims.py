"""[B] Trang: Claims."""
from collections import Counter

import pandas as pd
import streamlit as st

from core import queries
from core.claims import ClaimError
from ui import shared, view

shared.header("Claims", "Khiếu nại gửi hãng cho các khoản doanh nghiệp nhận thiếu. Con người duyệt trước khi gửi; "
              "ShipAudit chỉ ghi nhận trạng thái, không tự gửi hãng.")
db, now = shared.db(), shared.now()
names = shared.carrier_names()

counts = Counter(c["status"] for c in queries.list_claims(db))
c = st.columns(len(view.CLAIM_STATUS_LABELS))
for col, (status, label) in zip(c, view.CLAIM_STATUS_LABELS.items()):
    col.metric(label, counts.get(status, 0))

f = st.columns([1, 1, 1])
status = f[0].selectbox("Trạng thái", [None, *view.CLAIM_STATUS_LABELS], key="cl_status",
                        format_func=lambda s: "Tất cả" if s is None else view.CLAIM_STATUS_LABELS[s])
carrier = shared.carrier_select(names, "cl_carrier", f[1])
f[2].write("")
if f[2].button("Chuyển claim quá hạn sang Quá hạn", key="expire",
               help="Claim nháp hoặc đã duyệt mà quá hạn khiếu nại thì không gửi được nữa."):
    n = shared.claim_service().expire_overdue()
    shared.track("claim_expire_overdue", count=n)
    shared.flash(f"Đã chuyển {n} claim sang Quá hạn.")
    st.rerun()

claims = queries.list_claims(db, status, carrier)
if not claims:
    st.info("Chưa có claim nào với bộ lọc này. Tạo claim nháp ở trang Chi tiết đơn hoặc Hạn khiếu nại.")
    st.stop()

st.dataframe(pd.DataFrame(view.claim_rows(claims, names, now)), hide_index=True,
             column_config=shared.money_columns("Số tiền"))

# ── Duyệt hàng loạt (claim nháp, vẫn do con người duyệt) ──
drafts = [c for c in claims if c["status"] == "DRAFT"]
if drafts:
    with st.expander(f"Duyệt hàng loạt {len(drafts)} claim nháp"):
        st.caption("Mỗi claim vẫn được kiểm tra hạn khiếu nại khi duyệt; claim đã quá hạn bị bỏ qua và báo lại.")
        picked = st.multiselect(
            "Chọn claim", [c["claim_id"] for c in drafts], key="bulk_pick",
            format_func=lambda i: next(f"{i} · {c['order_code']} · {view.vnd(c['amount'])}" for c in drafts if c["claim_id"] == i),
        )
        b = st.columns([2, 1, 1], vertical_alignment="bottom")
        bulk_person = b[0].text_input("Tên người duyệt", key="bulk_person", placeholder="Ví dụ: Kế toán Lan")
        pick_all = b[1].checkbox("Chọn tất cả nháp", key="bulk_all")
        if b[2].button("Duyệt các claim đã chọn", key="bulk_approve", disabled=not bulk_person.strip()):
            ids = [c["claim_id"] for c in drafts] if pick_all else picked
            svc_bulk, done, failed = shared.claim_service(), 0, []
            for cid in ids:
                try:
                    svc_bulk.approve(cid, bulk_person)
                    done += 1
                except ClaimError as e:
                    failed.append(str(e))
            shared.track("claim_bulk_approve", approved=done, failed=len(failed))
            shared.flash(f"Đã duyệt {done} claim." + (f" Bỏ qua {len(failed)}: {'; '.join(failed[:3])}" if failed else ""))
            st.rerun()

# ── Xử lý một claim ──
st.subheader("Xử lý claim")
by_id = {c["claim_id"]: c for c in claims}
claim_id = st.selectbox(
    "Chọn claim", list(by_id), key="cl_pick",
    format_func=lambda i: f"{i} · {by_id[i]['order_code']} · {view.vnd(by_id[i]['amount'])} · "
                          f"{view.CLAIM_STATUS_LABELS[by_id[i]['status']]}",
)
claim = by_id[claim_id]
svc = shared.claim_service()


def act(action: str, fn) -> None:
    try:
        updated = fn()
    except ClaimError as e:
        st.error(str(e))
        return
    shared.track(f"claim_{action}", claim_id=claim_id, status=updated["status"])
    shared.flash(f"Claim {claim_id}: {view.CLAIM_STATUS_LABELS[updated['status']]}.")
    st.rerun()


with st.container(border=True):
    c = st.columns(3)
    c[0].metric("Số tiền khiếu nại", view.vnd(claim["amount"]))
    c[1].metric("Trạng thái", view.CLAIM_STATUS_LABELS[claim["status"]])
    c[2].metric("Hạn khiếu nại", view.dt_vn(claim.get("claim_deadline_at")),
                help=view.time_left(claim.get("claim_deadline_at"), now))
    st.caption(f"{view.DIFF_TYPE_LABELS.get(claim['diff_type'], claim['diff_type'])} · đơn {claim['order_code']} · "
               f"bảng kê {claim['statement_id']} · {names.get(claim['carrier'], claim['carrier'])}")

    person = st.text_input("Tên người thao tác", key="cl_person", placeholder="Ví dụ: Kế toán Lan")
    if claim["status"] == "DRAFT":
        st.write("Kiểm tra từng khoản ở trang Chi tiết đơn, rồi duyệt để chuyển sang chờ gửi hãng.")
        if st.button("Duyệt claim", type="primary", key="approve"):
            act("approve", lambda: svc.approve(claim_id, person))
    elif claim["status"] == "APPROVED":
        st.write("Gửi khiếu nại cho hãng (ngoài hệ thống), rồi ghi nhận đã gửi.")
        if st.button("Ghi nhận đã gửi hãng", type="primary", key="submit", disabled=not person.strip()):
            act("submit", lambda: svc.submit(claim_id, person.strip()))
    elif claim["status"] == "SUBMITTED":
        r = st.columns(2)
        amount = r[0].number_input("Số tiền hãng hoàn lại (₫)", min_value=0, value=int(claim["amount"]),
                                   step=1_000, key="cl_amount")
        if r[0].button("Ghi nhận đã thu hồi", type="primary", key="recover", disabled=not person.strip()):
            act("recover", lambda: svc.mark_recovered(claim_id, int(amount), person.strip()))
        note = r[1].text_input("Lý do hãng từ chối", key="cl_note")
        if r[1].button("Ghi nhận bị từ chối", key="reject", disabled=not person.strip()):
            act("reject", lambda: svc.mark_rejected(claim_id, person.strip(), note))
    else:
        st.write("Claim đã đóng, không còn thao tác.")

    if st.button("Xem chi tiết đơn", key="cl_open"):
        st.session_state["order_code"] = claim["order_code"]
        st.switch_page("screens/2_Chi_tiet_don.py")

    st.markdown("**Lịch sử**")
    st.dataframe(pd.DataFrame([{
        "Lúc": view.dt_vn(h["at"]),
        "Trạng thái": view.CLAIM_STATUS_LABELS.get(h["status"], h["status"]),
        "Người / nguồn": view.SOURCE_LABELS.get(h["by"], h["by"]),
    } for h in claim.get("history", [])]), hide_index=True)
