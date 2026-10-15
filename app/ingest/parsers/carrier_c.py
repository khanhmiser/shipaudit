"""[A] Parser Carrier C. Định dạng mẫu: CSV có cột note: tracking,cod,total_fee,note,net.
Mẫu thử: contracts/samples/statement_carrier_c.csv
"""
from app.ingest.parsers.base import StatementParser


class CarrierCParser(StatementParser):
    carrier = "carrier_c"

    def parse(self, raw: bytes, statement_id: str) -> list[dict]:
        # TODO(A): đọc CSV, chuẩn hóa về schema statement_lines.
        raise NotImplementedError
