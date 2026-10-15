"""[B] Streamlit. Đọc Mongo qua core.queries (không đi qua API của A)."""
import streamlit as st

st.set_page_config(page_title="ShipAudit", layout="wide")
st.title("ShipAudit")
st.caption("Đối soát cước vận tải: số phải nhận, chênh lệch, hạn khiếu nại.")
st.info("Khung ban đầu. Các trang nằm trong ui/pages/.")
