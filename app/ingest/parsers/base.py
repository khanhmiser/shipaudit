"""[A] Giao diện chung của parser bảng kê.

Mỗi parser đọc file thô của một hãng và trả về list[dict] đúng schema statement_lines.
Dòng hỏng: ghi log và bỏ qua, không làm sập cả file.
"""
from abc import ABC, abstractmethod


class StatementParser(ABC):
    carrier: str

    @abstractmethod
    def parse(self, raw: bytes, statement_id: str) -> list[dict]:
        ...
