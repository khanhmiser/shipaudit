"""[B] Trang: Chi tiết đơn / điều tra đơn (theo bản thiết kế docs/design/Investigate.dc.html)."""
import pandas as pd
import streamlit as st

from core import queries
from core.claims import OPEN_STATUSES, ClaimError
from core.periods import as_aware
from ui import detail, shared, view

db, now = shared.db(), shared.now()
names = shared.carrier_names()

# Mã đơn đến từ liên kết (?order=...), từ trang khác (session_state) hoặc người dùng gõ vào ô tìm.
incoming = (st.query_params.get("order") or st.session_state.get("order_code") or "").strip()
if st.session_state.get("_incoming") != incoming:
    st.session_state["order_input"] = incoming
    st.session_state["_incoming"] = incoming
head = st.container()
code = st.text_input("Mã đơn", key="order_input", placeholder="Ví dụ: A-0192").strip()

crumb_home = view.page_link("chenh-lech", "← Chênh lệch")
if not code:
    with head:
        shared.topbar("Chi tiết đơn", "Nhập mã đơn, hoặc mở một dòng ở trang Chênh lệch.", crumb=crumb_home)
    st.info("Nhập mã đơn, hoặc chọn một đơn ở trang Chênh lệch.")
    st.stop()

data = queries.order_detail(db, code)
order, recs = data["order"], sorted(data["reconciliations"], key=lambda r: r["statement_id"])
if order is None and not data["lines"]:
    with head:
        shared.topbar("Chi tiết đơn", f"Không tìm thấy đơn {code}.", crumb=crumb_home)
    st.warning(f"Không tìm thấy đơn {code}.")
    st.stop()
if not recs:
    lost = order is not None and order.get("status") == "LOST"
    with head:
        shared.topbar(code, "Đơn thất lạc" if lost else "Đơn chưa có bản ghi đối soát (chưa có bảng kê nào nhắc tới).",
                      crumb=crumb_home, mono=True)
    if lost:
        st.info("Đơn thất lạc: hãng không ghi đơn này vào bảng kê và đối soát không tính khoản nào. "
                "Bồi thường thất lạc nằm ngoài công thức đối soát, xử lý theo chính sách bồi thường của hãng.")
    else:
        st.info("Đơn chưa được đối soát. Khi bảng kê chứa đơn này được nạp, kết quả sẽ hiện ở đây.")
    st.stop()


def _pick(items: list[dict]) -> dict:
    """Bản ghi đối soát chính của đơn: ưu tiên khoản chênh lệch lớn nhất, không có thì bản ghi mới nhất."""
    diffs = [r for r in items if r["diff_type"] != "NONE"]
    return max(diffs, key=lambda r: abs(r.get("diff", 0))) if diffs else items[-1]


rec = _pick(recs)
if len(recs) > 1:
    ids = [r["reconciliation_id"] for r in recs]
    chosen = st.selectbox("Bảng kê", ids, index=ids.index(rec["reconciliation_id"]), key="rec_pick",
                          format_func=lambda i: next(f"{r['statement_id']} · {view.DIFF_TYPE_LABELS.get(r['diff_type'], r['diff_type'])}"
                                                     for r in recs if r["reconciliation_id"] == i))
    rec = next(r for r in recs if r["reconciliation_id"] == chosen)
rid = rec["reconciliation_id"]
carrier = rec["carrier"]
rule = queries.carrier_rule(db, carrier)

mine = [c for c in data["claims"] if c["reconciliation_id"] == rid]
claim = next((c for c in mine if c["status"] in OPEN_STATUSES), mine[0] if mine else None)
deadline = rec.get("claim_deadline_at")
hours = view.hours_left(deadline, now)
owed = rec.get("diff", 0) > 0 and rec["diff_type"] != "NONE"

with head:
    extra = view.badge(names.get(carrier, carrier), "muted") + (
        view.urgency_html(hours) if owed else view.badge(view.DIFF_TYPE_LABELS[rec["diff_type"]],
                                                         "success" if rec["diff_type"] == "NONE" else "muted"))
    shared.topbar(code, f"{view.DIFF_TYPE_LABELS.get(rec['diff_type'], rec['diff_type'])} · {view.period_label(rec.get('period'))}",
                  crumb=f"{crumb_home} / {view.esc(code)}", title_extra=extra, mono=True)

# ── Thông tin đơn ──
if order:
    k = st.columns(4)
    k[0].html(view.kpi("Trạng thái", view.ORDER_STATUS_LABELS.get(order["status"], order["status"]), names.get(carrier, carrier)))
    k[1].html(view.kpi("Ngày giao", view.dt_vn(order.get("delivered_at")), f"Kỳ {view.period_label(rec.get('period'))}"))
    k[2].html(view.kpi("Tiền thu hộ", view.vnd(order.get("cod_amount", 0)),
                       f"Giá trị khai báo {view.vnd(order.get('declared_value', 0))}"))
    k[3].html(view.kpi("Vùng giao", view.REGION_LABELS.get(order.get("region"), order.get("region") or "—"),
                       f"{order.get('weight_g', 0):,} g · {order.get('length_cm') or 0}×{order.get('width_cm') or 0}×"
                       f"{order.get('height_cm') or 0} cm".replace(",", ".")))
else:
    st.warning("Có dòng bảng kê mang mã này nhưng không khớp đơn nào của doanh nghiệp.")

why = detail.why_diff(rec, order, rule, names)
left, right = st.columns([3, 2])

with left:
    show_zero = st.toggle("Hiện cả các khoản bằng 0", key="show_zero")
    st.html(view.card("Đối chiếu số tiền", detail.breakdown_table(rec, show_zero),
                      '<span class="sa-subtle" style="font-size:12px">phải nhận theo quy tắc · thực nhận theo bảng kê · ₫</span>',
                      body_style="padding:0 0 8px"))
    if rec.get("actual_breakdown") is None and not rec.get("unmatched"):
        st.info("Đơn không có dòng nào trong bảng kê này, nên số tiền thực nhận là 0.")
    if rec.get("duplicate_lines"):
        st.warning(f"Bảng kê có {rec['duplicate_lines']} dòng trùng mã đơn này; đối soát dùng dòng cuối.")
    if rec.get("arrived_late"):
        st.info("Đơn này đã xuất hiện ở bảng kê kỳ sau (chuyển chậm). Kiểm tra lại trước khi khiếu nại.")
    st.caption(view.FORMULA_TEXT + f" Quy tắc hãng bản {rec.get('rule_version', '—')}.")

    st.html(view.card("Vì sao lệch", detail.why_html(why)))
    events = detail.timeline_events(rec, order, data["lines"], claim, now)
    st.html(view.card("Dòng thời gian", detail.timeline_html(events),
                      '<span class="sa-subtle" style="font-size:12px">từ dữ liệu đối soát</span>'))

    if data["lines"]:
        with st.expander("Dòng bảng kê gốc (bằng chứng cho claim)"):
            for line in data["lines"]:
                st.caption(f"{line['statement_id']} · nhận lúc {view.dt_vn(line.get('ingested_at'))}")
                st.dataframe(pd.DataFrame([line.get("raw") or {}]).astype(str), hide_index=True)
    if order:
        with st.expander("Thông tin khác của đơn"):
            st.dataframe(pd.DataFrame([
                ("Doanh nghiệp trả trước", view.vnd(order.get("prepaid_by_shop", 0))),
                ("Doanh nghiệp trả phí khi trả hàng", view.vnd(order.get("return_fee_paid_by_shop", 0))),
                ("Số ngày lưu kho", order.get("storage_days", 0)),
                ("Số lần đổi địa chỉ", order.get("address_changes", 0)),
                ("Đồng kiểm", "Có" if order.get("inspection") else "Không"),
                ("Khuyến mãi", view.vnd(order.get("promotion", 0))),
            ], columns=["Thông tin", "Giá trị"]).astype(str), hide_index=True)

with right:
    if owed:
        tone = view.deadline_tone(hours)
        pct = 0 if not hours or hours <= 0 else hours / view.HORIZON_HOURS * 100
        body = (f'<div class="sa-big sa-{"subtle" if tone == "muted" else ("" if tone == "primary" else tone)}">'
                f'{view.esc(view.time_left(deadline, now).replace("Còn ", ""))}</div>'
                f'<div style="margin:14px 0 10px">{view.track(pct, tone)}</div>'
                f'<div class="sa-muted" style="font-size:13px">Hạn: {view.esc(view.dt_vn(deadline))}. '
                f'{view.esc(detail.claim_window_text(rule, names, carrier))}</div>')
        st.html(view.card("Hạn khiếu nại", body, alert=tone == "danger"))
    else:
        st.html(view.card("Hạn khiếu nại", '<div class="sa-muted">Không có khoản doanh nghiệp nhận thiếu, '
                                           'không cần khiếu nại.</div>'))

    if owed:
        with st.container(border=True):
            st.markdown("**Soạn khiếu nại**")
            message = st.text_area("Nội dung gửi hãng", detail.claim_message(rec, why, names.get(carrier, carrier)),
                                   key=f"msg_{rid}", height=260)
            st.download_button("Tải nội dung (.txt)", message.encode("utf-8"), f"khieu-nai-{code}.txt", "text/plain",
                               key=f"dl_{rid}")
            st.caption("ShipAudit không tự gửi hãng: người duyệt kiểm tra, gửi ngoài hệ thống rồi ghi nhận ở trang Claims.")
            if claim and claim["status"] in OPEN_STATUSES:
                st.info(f"Đã có claim {claim['claim_id']} ({view.CLAIM_STATUS_LABELS[claim['status']]}), "
                        f"số tiền {view.vnd(claim['amount'])}. Xử lý ở trang Claims.")
            elif deadline is not None and as_aware(deadline) <= now:
                st.caption("Đã quá hạn khiếu nại, không tạo claim được.")
            elif st.button(f"Tạo claim nháp {view.vnd(rec['diff'])}", key=f"draft_{rid}", type="primary"):
                try:
                    created = shared.claim_service().create_draft(rid, "manual")
                except ClaimError as e:
                    st.error(str(e))
                else:
                    shared.track("claim_draft", claim_id=created["claim_id"], reconciliation_id=rid)
                    shared.flash(f"Đã tạo claim nháp {created['claim_id']}. Người duyệt xử lý ở trang Claims.")
                    st.rerun()
    st.html(view.card("Đường đi phục hồi", detail.steps_html(detail.recovery_steps(rec, claim))))
st.html(view.footnote())
