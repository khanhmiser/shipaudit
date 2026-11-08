"""[B] Trang: Claims."""
from collections import Counter
from datetime import datetime, time

import pandas as pd
import streamlit as st

from core import queries
from core.claims import ClaimError
from core.periods import VN_TZ
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
if not shared.read_only() and f[2].button("Chuyển claim quá hạn sang Quá hạn", key="expire",
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
if drafts and not shared.read_only():
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
            svc_bulk, approved, failed = shared.claim_service(), [], []
            for cid in ids:
                try:
                    approved.append(svc_bulk.approve(cid, bulk_person))
                except ClaimError as e:
                    failed.append(str(e))
            done = len(approved)
            shared.track("claim_bulk_approve", approved=done, failed=len(failed),
                         carrier=",".join(sorted({c["carrier"] for c in approved})), amount=sum(c["amount"] for c in approved))
            shared.claim_event("approved", approved, bulk_person.strip())
            shared.flash(f"Đã duyệt {done} claim." + (f" Bỏ qua {len(failed)}: {'; '.join(failed[:3])}" if failed else ""))
            st.rerun()

# ── Ghi nhận hãng đã hoàn tiền hàng loạt (claim đã gửi hãng) ──
sent = [c for c in claims if c["status"] == "SUBMITTED"]
if sent and not shared.read_only():
    with st.expander(f"Ghi nhận hãng đã hoàn tiền cho {len(sent)} claim đã gửi"):
        st.caption("Dùng khi hãng chấp nhận và hoàn đủ số tiền khiếu nại. Hãng hoàn thiếu hoặc từ chối thì xử lý từng claim ở dưới.")
        picked_sent = st.multiselect(
            "Chọn claim", [c["claim_id"] for c in sent], key="bulk_recover_pick",
            format_func=lambda i: next(f"{i} · {c['order_code']} · {view.vnd(c['amount'])}" for c in sent if c["claim_id"] == i),
        )
        b = st.columns([2, 1, 1], vertical_alignment="bottom")
        rec_person = b[0].text_input("Tên người ghi nhận", key="bulk_recover_person", placeholder="Ví dụ: Kế toán Lan")
        pick_all_sent = b[1].checkbox("Chọn tất cả", key="bulk_recover_all")
        if b[2].button("Ghi nhận đã thu hồi đủ", key="bulk_recover", disabled=not rec_person.strip()):
            ids = [c["claim_id"] for c in sent] if pick_all_sent else picked_sent
            svc_rec, recovered, failed = shared.claim_service(), [], []
            amounts = {c["claim_id"]: int(c["amount"]) for c in sent}
            for cid in ids:
                try:
                    recovered.append(svc_rec.mark_recovered(cid, amounts[cid], rec_person.strip()))
                except ClaimError as e:
                    failed.append(str(e))
            done, total = len(recovered), sum(c["recovered_amount"] for c in recovered)
            shared.track("claim_bulk_recover", recovered=done, failed=len(failed), amount=total,
                         carrier=",".join(sorted({c["carrier"] for c in recovered})))
            shared.claim_event("recovered", recovered, rec_person.strip())
            shared.flash(f"Đã ghi nhận thu hồi {done} claim, tổng {view.vnd(total)}."
                         + (f" Bỏ qua {len(failed)}: {'; '.join(failed[:3])}" if failed else ""))
            st.rerun()

# ── Xử lý một claim ──
st.subheader("Chi tiết claim" if shared.read_only() else "Xử lý claim")
by_id = {c["claim_id"]: c for c in claims}
claim_id = st.selectbox(
    "Chọn claim", list(by_id), key="cl_pick",
    format_func=lambda i: f"{i} · {by_id[i]['order_code']} · {view.vnd(by_id[i]['amount'])} · "
                          f"{view.CLAIM_STATUS_LABELS[by_id[i]['status']]}",
)
claim = by_id[claim_id]
svc = shared.claim_service()


EVENT_OF = {"approve": "approved", "submit": "submitted", "recover": "recovered", "reject": "rejected",
            "followup": "followup"}


def act(action: str, fn) -> None:
    try:
        updated = fn()
    except ClaimError as e:
        st.error(str(e))
        return
    by = person.strip()
    shared.track(f"claim_{action}", claim_id=claim_id, claim_status=updated["status"], carrier=updated["carrier"],
                 amount=updated["amount"], alert_id=updated.get("alert_id"), by=by)
    shared.claim_event(EVENT_OF[action], [updated], by)
    shared.flash(f"Claim {claim_id}: {view.CLAIM_STATUS_LABELS[updated['status']]}."
                 + (" Đã ghi nhật ký theo dõi." if action == "followup" else ""))
    st.rerun()


def followup_form(prefix: str) -> None:
    """Ghi một lần trao đổi với hãng (gọi điện, email, họp...) kèm ngày hẹn liên hệ lại."""
    fu = st.columns([3, 1], vertical_alignment="bottom")
    text = fu[0].text_area("Nội dung trao đổi với hãng", key=f"{prefix}_fu_note", height=80,
                           placeholder="Ví dụ: Đã gọi hãng, gửi lại ảnh biên nhận; hãng hẹn trả lời trong 3 ngày")
    when = fu[1].date_input("Hẹn liên hệ lại", value=None, key=f"{prefix}_fu_date", format="DD/MM/YYYY")
    next_at = datetime.combine(when, time(9, 0), tzinfo=VN_TZ) if when else None
    if st.button("Ghi nhật ký theo dõi", key=f"{prefix}_fu_save", disabled=not (person.strip() and text.strip())):
        act("followup", lambda: svc.add_followup(claim_id, person.strip(), text, next_at))


with st.container(border=True):
    c = st.columns(3)
    c[0].metric("Số tiền khiếu nại", view.vnd(claim["amount"]))
    c[1].metric("Trạng thái", view.CLAIM_STATUS_LABELS[claim["status"]])
    c[2].metric("Hạn khiếu nại", view.dt_vn(claim.get("claim_deadline_at")),
                help=view.time_left(claim.get("claim_deadline_at"), now))
    st.caption(f"{view.DIFF_TYPE_LABELS.get(claim['diff_type'], claim['diff_type'])} · đơn {claim['order_code']} · "
               f"bảng kê {claim['statement_id']} · {names.get(claim['carrier'], claim['carrier'])}")

    if claim["status"] == "REJECTED":
        st.warning(f"Hãng từ chối: {claim.get('note') or 'chưa ghi lý do'}"
                   + (f" · hẹn liên hệ lại {view.dt_vn(claim['next_contact_at'])}" if claim.get("next_contact_at") else ""))

    person = "" if shared.read_only() else st.text_input("Tên người thao tác", key="cl_person",
                                                         placeholder="Ví dụ: Kế toán Lan")
    if shared.read_only():
        st.caption(shared.READ_ONLY_NOTE)
    elif claim["status"] == "DRAFT":
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
        note = r[1].text_input("Lý do hãng từ chối (bắt buộc)", key="cl_note",
                               placeholder="Ví dụ: thiếu ảnh biên nhận giao hàng")
        if r[1].button("Ghi nhận bị từ chối", key="reject", disabled=not (person.strip() and note.strip())):
            act("reject", lambda: svc.mark_rejected(claim_id, person.strip(), note))
        with st.expander("Ghi nhật ký trao đổi với hãng (đang chờ phản hồi)"):
            followup_form("sub")
    elif claim["status"] == "REJECTED":
        st.write("Hệ thống không tạo claim mới cho khoản này. Doanh nghiệp tự liên hệ hãng và ghi lại từng lần trao đổi "
                 "để theo dõi; nếu hãng đồng ý hoàn tiền thì ghi nhận đã thu hồi.")
        followup_form("rej")
        r = st.columns([1, 2], vertical_alignment="bottom")
        amount = r[0].number_input("Số tiền hãng đồng ý hoàn (₫)", min_value=0, value=int(claim["amount"]),
                                   step=1_000, key="rej_amount")
        if r[1].button("Hãng đồng ý hoàn sau khi liên hệ: ghi nhận đã thu hồi", key="rej_recover",
                       disabled=not person.strip()):
            act("recover", lambda: svc.mark_recovered(claim_id, int(amount), person.strip()))
    else:
        st.write("Claim đã đóng, không còn thao tác.")

    if st.button("Xem chi tiết đơn", key="cl_open"):
        st.session_state["order_code"] = claim["order_code"]
        st.switch_page("screens/2_Chi_tiet_don.py")

    if claim.get("followups"):
        st.markdown("**Nhật ký theo dõi với hãng**")
        st.dataframe(pd.DataFrame([{
            "Lúc": view.dt_vn(f.get("at")),
            "Người theo dõi": f.get("by", ""),
            "Nội dung": f.get("note", ""),
            "Hẹn liên hệ lại": view.dt_vn(f["next_contact_at"]) if f.get("next_contact_at") else "",
        } for f in reversed(claim["followups"])]), hide_index=True)

    st.markdown("**Lịch sử**")
    st.dataframe(pd.DataFrame([{
        "Lúc": view.dt_vn(h["at"]),
        "Trạng thái": view.CLAIM_STATUS_LABELS.get(h["status"], h["status"]),
        "Người / nguồn": view.SOURCE_LABELS.get(h["by"], h["by"]),
    } for h in claim.get("history", [])]), hide_index=True)
