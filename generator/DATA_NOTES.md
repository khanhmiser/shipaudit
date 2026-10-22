# Ghi chú dữ liệu ShipAudit (bộ sinh tổng hợp)

Dữ liệu 100% tổng hợp, không dùng dữ liệu thật của công ty, không dùng Olist (chưa xác minh giấy phép).
Ba hãng là hãng giả (Carrier A/B/C). Cấu trúc phí tham khảo chính sách công khai của GHN/GHTK;
mức cước, tỷ lệ COD/hoàn/lỗi và tỷ lệ chênh lệch là GIẢ ĐỊNH của đội, không phản ánh thị trường.
Dữ liệu chỉ chứng minh hệ thống chạy đúng và tái lập được.

## Chạy

```
python -m generator.seed                      # sinh vào generator/out/ (seed=42, cố định)
python -m generator.load_mongo --db shipaudit_b_dev          # nạp (đọc MONGO_URI trong .env)
python -m generator.load_mongo --db shipaudit_b_dev --reset  # xóa 4 collection dữ liệu rồi nạp lại
```

Hoặc `mongoimport --uri "<URI>" --db shipaudit_b_dev --collection orders --file generator/out/orders.jsonl`
(tạo `ingest_events` dạng Time Series trước nếu nạp bằng mongoimport).
Sinh lại với `--now` khác để dời mốc "bây giờ" (đồng hồ khiếu nại tính theo mốc này).

## Trong generator/out/

| File | Nội dung |
|---|---|
| carrier_rules.jsonl | 3 hãng. Có thêm `claim_anchor`, `payout_basis`, `status_policy` (đều chờ chốt) |
| orders.jsonl | 5.308 đơn, 8 tuần ISO (W35..W42/2026) |
| statement_lines.jsonl | 5.241 dòng bảng kê đã chuẩn hóa, 24 bảng kê (3 hãng x 8 tuần) |
| ingest_events.jsonl | Sự kiện nạp (Time Series), lô 25 dòng |
| labels.json | ĐÁP ÁN: mỗi dòng có diff_type, subtype, expected_amount, actual_amount, diff, breakdown |
| raw/*.csv | 24 bảng kê thô đúng 3 định dạng của contracts/samples/ (cho parser của A) |
| manifest.json | Số lượng và tóm tắt |

`reconciliations` và `claims` KHÔNG có sẵn: đó là kết quả engine sinh ra. Dùng `labels.json` để kiểm tra engine
(engine phải ra cùng expected_amount, diff, diff_type cho từng (statement_id, order_code)).

## Quy ước

- Tiền là số nguyên VNĐ. `diff = expected_amount - actual_amount` (dương = hãng trả thiếu).
- `LATE_PAYOUT`: đơn nằm ở bảng kê kỳ SAU kỳ giao (`delivery_period` trong labels), diff = 0.
- `MISSING_IN_STATEMENT`: không có dòng trong statement_lines, actual_amount = 0.
- Đơn `LOST` (27 đơn) không có dòng và không bị tính là thiếu (nhãn nằm ở `excluded`).
- Cột "net" của bảng kê đã cộng lại khoản shop trả trước (không có cột riêng): so với `orders.prepaid_by_shop`.
- Carrier C gộp bảo hiểm và phí hoàn vào `total_fee`, nên `statement_lines.shipping_fee` của C = total_fee.
  Đổi địa chỉ (5.000đ) trừ ngoài total_fee, ghi chú "doi dia chi".
- Kỳ = tuần ISO giờ VN, nhãn `2026-W41`. `cod_payout_days` tính từ cuối kỳ.
- Khoản chưa có dữ liệu: khuyến mãi, shop trả phí khi trả hàng, phí đồng kiểm (đều bằng 0).

## Kịch bản sự cố nghiệp vụ (mặc định bật, tắt bằng --no-incident)

Kỳ W42 của Carrier C: một nửa số đơn nội miền/liên miền bị tính thêm một bậc khối lượng (`subtype=C_STEP_CHANGE`,
`incident=true`) làm tỷ lệ FEE_MISMATCH vọt lên so với nền, để monitor "chênh lệch vượt ngưỡng" có việc để bắt.
Đồng hồ khiếu nại ở mốc `--now`: C còn 18 giờ (hạn 24), A còn 52 giờ (hạn 72), B còn 128 giờ (hạn 168).

## Trường mở rộng ngoài contracts v0.1.0 (đề xuất v0.2.0, cần PR duyệt chung với A)

- `orders`: `address_changed` (bool), `inspected` (bool), `storage_days` (int).
- `statement_lines`: `paid_at` (ngày hãng chuyển tiền, để phát hiện LATE_PAYOUT).
- `carrier_rules`: `claim_anchor`, `payout_basis`, `status_policy`.
Engine có thể bỏ qua các trường này, nhưng kiểm tra phí lưu kho/đổi địa chỉ và LATE_PAYOUT cần đến chúng.

## Khai báo cho bài nộp (mục 12) và nhật ký

- docs/reuse-and-data.md: dữ liệu tổng hợp do generator/ sinh; chính sách GHN/GHTK chỉ dùng tham khảo cấu trúc phí;
  Olist chưa dùng (chưa xác minh giấy phép).
- docs/ai-usage-log.md: 22/10/2026 · Claude (Anthropic) · viết generator/ (fee_model, synthetic, inject, statements,
  seed, load_mongo) và tests/generator/ · người kiểm tra: (điền tên).
