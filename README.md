# ShipAudit

Đối soát cước vận tải 3PL theo quy tắc từng hãng: tính **số tiền phải nhận** của từng đơn,
so với **số tiền thực nhận**, cảnh báo chênh lệch theo hạn khiếu nại.

MUGVN Hackathon 2026 · Real-time Operations (MongoDB x Datadog).
Chỉ dùng dữ liệu tổng hợp hoặc dataset công khai. Hãng vận chuyển trong demo là hãng giả (Carrier A/B/C).

## Phân công

| | Phạm vi | Thư mục chính |
|---|---|---|
| **A** | Đường ống và quan sát: nạp dữ liệu, API, Change Streams, telemetry, Datadog vận hành, webhook | `app/`, `datadog/ops/`, `scenarios/ops/` |
| **B** | Đúng sai của con số: dữ liệu, quy tắc hãng, engine, pipeline, Streamlit, Datadog nghiệp vụ | `core/`, `pipelines/`, `generator/`, `ui/`, `datadog/biz/`, `scenarios/biz/` |

Chi tiết: `docs/ShipAudit_Ke-hoach-ky-thuat_AB.docx`. Tiến độ cập nhật ở mục 10 của file đó.

## Quy tắc ngắn

- `main` luôn chạy được. Mỗi người một nhánh feature, PR nhỏ, người kia duyệt trong 12 giờ.
- Hai bên chỉ chạm nhau qua `contracts/`. Đổi contract thì sửa cùng PR và tăng `contracts/VERSION`.
- `core/` không import từ `app/`. `ui/` chỉ đọc qua `core/queries.py`.
- Tiền là số nguyên VNĐ (hoặc `Decimal`), không dùng float.
- Ghi công cụ AI đã dùng vào `docs/ai-usage-log.md`, thư viện và dataset ngoài vào `docs/reuse-and-data.md`.

## Chạy thử (cập nhật dần khi code xong)

```bash
cp .env.example .env        # điền MONGO_URI, DD_API_KEY...
pip install -e ".[dev]"
make test                   # chạy test
make up                     # docker compose up: api + ui + datadog-agent
make seed                   # sinh dữ liệu tổng hợp (khi B xong generator)
```

## Cấu trúc

Xem `docs/ShipAudit_Ke-hoach-ky-thuat_AB.docx` mục 7. Mỗi thư mục có docstring ở file chính nêu việc của nó.
