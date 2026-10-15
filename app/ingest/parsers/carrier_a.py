"""[A] Parser Carrier A. Định dạng mẫu: CSV dấu phẩy: order_code,cod_amount,ship_fee,insurance,return_fee,transfer_fee,net_paid.
Mẫu thử: contracts/samples/statement_carrier_a.csv
"""
from app.ingest.parsers.base import StatementParser


class CarrierAParser(StatementParser):
    carrier = "carrier_a"

    def parse(self, raw: bytes, statement_id: str) -> list[dict]:
        # TODO(A): đọc CSV, chuẩn hóa về schema statement_lines.
        raise NotImplementedError
