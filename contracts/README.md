# contracts/

Nguồn sự thật chung của A và B. Mọi thay đổi đi qua PR, người kia duyệt.
Đổi gì ở đây thì tăng số trong `VERSION` và báo người kia trong buổi họp tối.

- `schemas/`: JSON Schema của 6 collection (khớp bản chốt kiến trúc dữ liệu).
- `samples/`: 3 file bảng kê mẫu, mỗi hãng một định dạng (B viết, A dùng làm parser). Dữ liệu tổng hợp.
- `interfaces.py`: Protocol và bản stub cho 3 điểm tiếp xúc (reconcile_statement, claims, metric).

Quy ước tên metric: A dùng `shipaudit.ops.*`, B dùng `shipaudit.biz.*`.
