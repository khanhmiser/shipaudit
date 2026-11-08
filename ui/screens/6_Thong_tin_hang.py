"""[B] Trang: Thông tin hãng. Quy tắc từng hãng đọc từ carrier_rules (chỉ xem, không sửa ở đây)."""
import pandas as pd
import streamlit as st

from core import queries
from ui import shared, view

shared.header("Thông tin hãng", "Quy tắc tính tiền của từng hãng vận chuyển, đọc từ dữ liệu `carrier_rules`. "
              "Số tiền phải nhận của mỗi đơn được tính theo đúng các quy tắc này.")
rules = queries.carrier_rule_documents(shared.db())
if not rules:
    st.info("Chưa có quy tắc hãng nào trong cơ sở dữ liệu.")
    st.stop()

ANCHOR = {"statement_received_at": "lúc nhận bảng kê", "delivered_at": "ngày giao đơn"}
PAYOUT = {"delivered_plus_days": "ngày giao + số ngày trả", "period_end": "cuối kỳ giao hàng + số ngày trả"}
POLICY_COLS = (("collect_cod", "Chuyển tiền thu hộ"), ("charge_shipping", "Tính phí giao hàng"),
               ("charge_return", "Tính phí chuyển hoàn"))


def pct(bp: int) -> str:
    return f"{bp / 100:g}%"


def fee(amount: int | None) -> str:
    return view.vnd(amount) if amount else "Không thu"


def window(hours: int) -> str:
    return f"{hours} giờ" + (f" ({hours // 24} ngày)" if hours % 24 == 0 and hours >= 48 else "")


def surcharge_rows(r: dict) -> list[dict]:
    s = r.get("surcharges") or {}
    ins, ret, sto = s.get("insurance") or {}, s.get("return") or {}, s.get("storage") or {}
    ret_text = " + ".join(t for t in (view.vnd(ret["fixed"]) if ret.get("fixed") else "",
                                      f"{pct(ret['rate_bp'])} phí giao hàng" if ret.get("rate_bp") else "") if t) or "Miễn phí"
    flat = ret.get("flat_by_region") or {}
    if flat:
        ret_text += "; riêng " + ", ".join(f"{view.REGION_LABELS.get(k, k).lower()} {view.vnd(v)}" for k, v in flat.items())
    rows = [
        ("Bảo hiểm", f"{pct(ins['rate_bp'])} giá trị khai báo, áp dụng từ {view.vnd(ins['min_declared_value'])}" if ins else "—"),
        ("Phí chuyển hoàn", ret_text if ret else "—"),
        ("Phí lưu kho", (f"{view.vnd(sto['per_day'])}/ngày, miễn phí {sto['free_days']} ngày đầu" if sto.get("per_day") else "Không thu") if sto else "—"),
        ("Phí thay đổi địa chỉ", fee((s.get("address_change") or {}).get("fixed")) if s.get("address_change") else "—"),
        ("Phí đồng kiểm", fee((s.get("inspection") or {}).get("fixed")) if s.get("inspection") else "—"),
        ("Phí chuyển khoản", (view.vnd(r.get("transfer_fee", 0)) + (" mỗi đơn có thu hộ" if r.get("transfer_fee_cod_only") else " mỗi đơn"))
         if r.get("transfer_fee") else "Không thu"),
    ]
    return [{"Khoản": k, "Quy tắc": v} for k, v in rows]


def rate_frame(r: dict) -> pd.DataFrame:
    table = r.get("rate_table") or []
    if not table:
        return pd.DataFrame()
    maxes = [b["max_weight_g"] for b in table[0]["brackets"]]
    data = {}
    for reg in table:
        by_max = {b["max_weight_g"]: b["fee"] for b in reg["brackets"]}
        col = [view.vnd(by_max.get(m)) for m in maxes]
        col.append(f"+ {view.vnd(reg['extra_fee'])} mỗi {reg['extra_step_g']} g thêm")
        data[view.REGION_LABELS.get(reg["region"], reg["region"])] = col
    return pd.DataFrame(data, index=[f"Đến {m:,} g".replace(",", ".") for m in maxes] + ["Vượt mốc cuối"])


# ── So sánh nhanh các hãng, cùng một thước đo ──
st.subheader("Các điểm khác nhau chính")
st.dataframe(pd.DataFrame([{
    "Hãng": r.get("display_name") or r["carrier"],
    "Hệ số khối lượng quy đổi": r["dim_weight_divisor"],
    "Trả tiền thu hộ sau": f"{r['cod_payout_days']} ngày",
    "Hạn khiếu nại": window(r["claim_window_hours"]),
    "Phí chuyển khoản": fee(r.get("transfer_fee")),
    "Phiên bản quy tắc": r.get("version"),
} for r in rules]), hide_index=True)
st.caption("Các hãng được đặt cạnh nhau để so sánh, không xếp hạng hay đánh giá hãng. "
           "Dữ liệu tổng hợp, hãng giả định Carrier A/B/C; tham số là kịch bản giả định.")

# ── Chi tiết từng hãng ──
st.subheader("Chi tiết từng hãng")
tabs = st.tabs([r.get("display_name") or r["carrier"] for r in rules])
for tab, r in zip(tabs, rules):
    with tab:
        c1, c2, c3 = st.columns(3)
        c1.metric("Hạn khiếu nại", window(r["claim_window_hours"]),
                  help=f"Tính từ {ANCHOR.get(r.get('claim_deadline_anchor', 'statement_received_at'), '—')}.")
        c2.metric("Trả tiền thu hộ", f"{r['cod_payout_days']} ngày",
                  help=f"Mốc: {PAYOUT.get(r.get('payout_basis', 'delivered_plus_days'), '—')}.")
        c3.metric("Hệ số khối lượng quy đổi", f"{r['dim_weight_divisor']:,}".replace(",", "."),
                  help="Khối lượng quy đổi = dài × rộng × cao (cm) ÷ hệ số này. Tính theo giá trị lớn hơn giữa thực tế và quy đổi.")

        st.markdown("**Bảng cước theo vùng và khối lượng**")
        frame = rate_frame(r)
        if frame.empty:
            st.caption("Chưa có bảng cước.")
        else:
            st.dataframe(frame)

        st.markdown("**Phụ phí**")
        st.dataframe(pd.DataFrame(surcharge_rows(r)), hide_index=True)

        policy = r.get("status_policy")
        st.markdown("**Cách tính theo trạng thái đơn**")
        if policy:
            st.dataframe(pd.DataFrame([{
                "Trạng thái": view.ORDER_STATUS_LABELS.get(status, status),
                **{label: "Có" if rule.get(key) else "Không" for key, label in POLICY_COLS},
            } for status, rule in policy.items()]), hide_index=True)
        else:
            st.caption("Hãng dùng quy tắc trạng thái mặc định của hệ thống.")
        st.caption(f"Cập nhật: {view.dt_vn(r.get('updated_at'))}")

st.info("Đây là phần chỉ để xem. Quy tắc hãng là dữ liệu trong `carrier_rules`: đổi tham số (cước, phụ phí, hạn khiếu nại) "
        "ở đó mà không cần sửa mã, sau đó đối soát lại để áp dụng cho các đơn.")
st.html(view.footnote())
