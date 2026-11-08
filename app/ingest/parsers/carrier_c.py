"""[A] Parser Carrier C. Định dạng mẫu: CSV có cột note: tracking,cod,total_fee,note,net.
Mẫu thử: contracts/samples/statement_carrier_c.csv

Hãng C gộp mọi phí vào total_fee, ghi vào shipping_fee. Ghi chú (note) chỉ giữ trong `raw`.
"""
from app.ingest.parsers.base import StatementParser


class CarrierCParser(StatementParser):
    carrier = "carrier_c"
    delimiter = ","
    columns = {
        "tracking": "order_code",
        "cod": "cod_collected",
        "total_fee": "shipping_fee",
        "net": "net_paid",
    }
    raw_only = ("note",)
