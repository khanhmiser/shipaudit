"""[A] Parser Carrier B. Định dạng mẫu: CSV dấu chấm phẩy: ma_don;thu_ho;cuoc_van_chuyen;phi_hoan;phi_luu_kho;thuc_tra.
Mẫu thử: contracts/samples/statement_carrier_b.csv
"""
from app.ingest.parsers.base import StatementParser


class CarrierBParser(StatementParser):
    carrier = "carrier_b"

    def parse(self, raw: bytes, statement_id: str) -> list[dict]:
        # TODO(A): đọc CSV, chuẩn hóa về schema statement_lines.
        raise NotImplementedError
