# Thành phần tái sử dụng và dữ liệu ngoài

Brief yêu cầu khai báo rõ. Không dùng dữ liệu thật của công ty.

## Dataset ngoài

| Dataset | Nguồn | Giấy phép | Dùng vào việc | Ghi chú |
|---|---|---|---|---|
| ShipAudit chat_v1 (tự sinh) | Claude (claude.ai) sinh cho đội, nằm ở `generator/out/chat_v1/` | Dữ liệu của đội, 100% tổng hợp | Dữ liệu demo chính: 3 hãng giả, 5.308 đơn, 24 bảng kê W35–W42/2026, labels.json làm đáp án | Cấu trúc phí tham khảo chính sách công khai GHN/GHTK; mức cước, tỷ lệ chênh lệch là giả định (kịch bản giả định) |
| Brazilian E-Commerce Public Dataset by Olist | Kaggle | **CHƯA XÁC MINH** (đọc mục License trên trang Kaggle) | Nền đơn hàng để lấy mẫu | Tiền đổi sang VNĐ bằng hệ số cố định; COD, hãng, bảng kê, chênh lệch là tự sinh |

## Tài liệu tham khảo công khai (dùng để đặt tham số hãng giả lập)

Chỉ dùng làm căn cứ đặt tham số và cách hiểu thuật ngữ cho Carrier A/B/C giả lập; không dùng dữ liệu thật của hãng nào, không khớp từng con số.

| Nguồn | Dùng vào việc |
|---|---|
| GHN: bài viết công khai về đối soát COD và công thức đối soát | Công thức tiền đối soát, khoản "trả trước", "trả phí khi trả hàng" |
| GHN: phí trả hàng, chuyển hoàn, giao 1 phần trả 1 phần, chính sách vận chuyển | `status_policy`, phí chuyển hoàn |
| GHN, GHTK: lịch đối soát và chuyển tiền thu hộ | Kỳ đối soát, `cod_payout_days` |
| GHTK: thanh toán tiền trả trước, tính năng cấn trừ | Nghĩa của khoản doanh nghiệp trả trước |
| Luật Bưu chính 2010, Điều 38 | Thời hiệu khiếu nại thực tế (1 tháng kể từ ngày phát với cước), lý do có `claim_deadline_anchor` |

## Thư viện và template

Ghi tên, phiên bản và giấy phép của thư viện/template đáng kể ngoài `pyproject.toml`.

| Thư viện | Phiên bản | Giấy phép | Dùng vào việc |
|---|---|---|---|
| mongomock | 4.3.0 | ISC | Mongo giả trong bộ nhớ cho test của B (`tests/core/`), chỉ là phụ thuộc dev |
| Streamlit | 1.66.1 | Apache-2.0 | Giao diện (`ui/`), kể cả `streamlit.testing` cho test giao diện |
| pandas | 3.0.6 | BSD-3-Clause | Bảng dữ liệu trên giao diện |
| Altair (Vega-Lite) | 6.3.0 | BSD-3-Clause | Biểu đồ trang So sánh hãng |
