"""[B] Streamlit. Đọc Mongo qua core.queries (không đi qua API của A).

Chạy: `streamlit run ui/app.py` từ gốc repo. Trang này chỉ dựng thanh điều hướng; nội dung ở ui/screens/.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # streamlit chỉ thêm ui/ vào sys.path
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from ui import view  # noqa: E402

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
    ],
})
st.sidebar.caption("Đối soát cước vận tải. Dữ liệu demo là dữ liệu tổng hợp, hãng giả định Carrier A/B/C.")
nav.run()
