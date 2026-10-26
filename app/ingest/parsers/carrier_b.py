"""[A] Parser Carrier B. Định dạng mẫu: CSV dấu chấm phẩy: ma_don;thu_ho;cuoc_van_chuyen;phi_hoan;phi_luu_kho;thuc_tra.
Mẫu thử: contracts/samples/statement_carrier_b.csv
"""
from app.ingest.parsers.base import StatementParser


class CarrierBParser(StatementParser):
    carrier = "carrier_b"
    delimiter = ";"
    columns = {
        "ma_don": "order_code",
        "thu_ho": "cod_collected",
        "cuoc_van_chuyen": "shipping_fee",
        "phi_hoan": "return_shipping_fee",
        "phi_luu_kho": "storage_fee",
        "thuc_tra": "net_paid",
    }
