"""[B] Streamlit. Đọc Mongo qua core.queries (không đi qua API của A).

Chạy: `streamlit run ui/app.py` từ gốc repo. Trang này chỉ dựng thanh điều hướng; nội dung ở ui/screens/.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # streamlit chỉ thêm ui/ vào sys.path
    sys.path.insert(0, str(ROOT))

import os  # noqa: E402

import streamlit as st  # noqa: E402


def _secrets_to_env() -> None:
    """Streamlit Community Cloud: đưa secrets cấp gốc (MONGO_URI, MONGO_DB, SHIPAUDIT_NOW, SHIPAUDIT_READ_ONLY...) vào
    biến môi trường trước khi common.config đọc. Chạy trên máy không có secrets.toml thì bỏ qua, dùng .env như cũ."""
    try:
        for key, value in st.secrets.items():
            if isinstance(value, (str, int, float, bool)):
                os.environ.setdefault(key, str(value))
    except Exception:  # noqa: BLE001  không có secrets.toml
        pass


_secrets_to_env()

from ui import shared, view  # noqa: E402

st.set_page_config(page_title="ShipAudit", page_icon=":material/receipt_long:", layout="wide")
st.logo(str(Path(__file__).parent / "assets" / "logo.svg"), size="large")
st.html(view.CSS)  # CSS dùng chung theo bản thiết kế docs/design/ (bảng màu AML)

nav = st.navigation({
    "Đối soát": [
        st.Page("screens/0_Tong_quan.py", title="Tổng quan", icon=":material/dashboard:", default=True),
        st.Page("screens/1_Chenh_lech.py", title="Chênh lệch", icon=":material/warning:", url_path="chenh-lech"),
        st.Page("screens/2_Chi_tiet_don.py", title="Chi tiết đơn", icon=":material/search:", url_path="chi-tiet-don"),
        st.Page("screens/3_Han_khieu_nai.py", title="Hạn khiếu nại", icon=":material/timer:", url_path="han-khieu-nai"),
        st.Page("screens/5_Claims.py", title="Claims", icon=":material/assignment:", url_path="claims"),
    ],
    "Phân tích": [
        st.Page("screens/4_So_sanh_hang.py", title="So sánh hãng", icon=":material/monitoring:", url_path="so-sanh-hang"),
        st.Page("screens/6_Thong_tin_hang.py", title="Thông tin hãng", icon=":material/local_shipping:", url_path="thong-tin-hang"),
    ],
})
st.sidebar.caption("Đối soát cước vận tải. Dữ liệu demo là dữ liệu tổng hợp, hãng giả định Carrier A/B/C.")
if shared.read_only():
    st.sidebar.info("Bản demo chỉ xem: số liệu và màn hình đầy đủ, các nút duyệt và ghi nhận được ẩn.")
nav.run()
