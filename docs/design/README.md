# Thiết kế giao diện ShipAudit (bảng màu AML)

Nguồn thiết kế từ Claude Design (3 màn: Tổng quan, Danh sách chênh lệch, Điều tra đơn).
- `aml-ui.css`: token màu + class thành phần (dark mặc định, có aml-light). Dùng làm nguồn tham chiếu khi viết CSS.
- `Main.dc.html`, `Cases.dc.html`, `Investigate.dc.html`: bố cục từng màn (mở bằng trình duyệt để xem).
- `canvas.json`: chỉ mục canvas.

## Ánh xạ sang Streamlit hiện có
| Màn thiết kế | File Streamlit |
|---|---|
| Tổng quan | ui/screens/0_Tong_quan.py |
| Danh sách chênh lệch | ui/screens/1_Chenh_lech.py (+ 3_Han_khieu_nai.py) |
| Điều tra đơn | ui/screens/2_Chi_tiet_don.py |

Cách áp dụng: đặt token vào `.streamlit/config.toml` (theme) và CSS bổ sung qua `st.markdown(<style>)` trong `ui/view.py`.
Dữ liệu trong thiết kế là tổng hợp (Carrier A/B/C). Công cụ AI: Claude Design/Claude Code (khai báo trong docs/ai-usage-log.md).
