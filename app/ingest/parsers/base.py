"""[A] Giao diện chung của parser bảng kê.

Mỗi parser đọc file thô của một hãng và trả về list[dict] đúng schema statement_lines
(contracts/schemas/statement_lines.json).
- Sai tiêu đề cột (thiếu cột, thừa cột lạ) hoặc file không đọc được: ném StatementFormatError, không nạp dòng nào.
- Dòng hỏng (thiếu mã đơn, tiền không phải số nguyên, sai số cột): ghi log và bỏ qua, không làm sập cả file.
- Tiền là số nguyên VNĐ, không dùng float. Ô tiền để trống coi là 0, trừ cột số tiền thực nhận (net_paid) bắt buộc có.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger("shipaudit.ingest.parser")

_INT = re.compile(r"[+-]?\d+")
REQUIRED_MONEY = ("net_paid",)


class StatementFormatError(ValueError):
    """Lỗi cấp file: sai tiêu đề cột hoặc không đọc được file."""


class RowError(ValueError):
    """Lỗi một dòng: dòng bị bỏ qua, các dòng khác vẫn nạp."""


@dataclass
class ParseResult:
    lines: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # mỗi dòng hỏng một thông báo "dòng N: ..."


def parse_money(value: str | None, field_name: str) -> int:
    s = (value or "").strip()
    if s == "":
        if field_name in REQUIRED_MONEY:
            raise RowError(f"{field_name} trống")
        return 0
    if not _INT.fullmatch(s):
        raise RowError(f"{field_name}={value!r} không phải số nguyên VNĐ")
    return int(s)


class StatementParser(ABC):
    carrier: str
    delimiter: str = ","
    # Cột trong file → trường statement_lines. Trường "order_code" là mã đơn, các trường còn lại là tiền.
    columns: dict[str, str]
    # Cột chỉ giữ lại trong `raw` (ví dụ ghi chú của hãng).
    raw_only: tuple[str, ...] = ()

    def parse(self, raw: bytes, statement_id: str, ingested_at: datetime | None = None) -> list[dict]:
        return self.parse_report(raw, statement_id, ingested_at).lines

    def parse_report(self, raw: bytes, statement_id: str, ingested_at: datetime | None = None) -> ParseResult:
        ingested_at = ingested_at or datetime.now(timezone.utc)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise StatementFormatError(f"{self.carrier}: file không phải UTF-8 ({e.reason})") from e

        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=self.delimiter, restkey="__extra__")
        header = [h.strip() for h in (reader.fieldnames or [])]
        expected = [*self.columns, *self.raw_only]
        if sorted(header) != sorted(expected):
            missing = [c for c in expected if c not in header]
            unknown = [c for c in header if c not in expected]
            raise StatementFormatError(
                f"{self.carrier}: sai tiêu đề cột, thiếu {missing or '[]'}, thừa {unknown or '[]'} "
                f"(cần: {self.delimiter.join(expected)})"
            )
        reader.fieldnames = header

        result = ParseResult()
        for row in reader:
            line_no = reader.line_num
            if not any((v or "").strip() for k, v in row.items() if k != "__extra__"):
                continue  # dòng trống
            try:
                result.lines.append(self._line(row, statement_id, ingested_at))
            except RowError as e:
                result.errors.append(f"dòng {line_no}: {e}")
                log.warning("bỏ qua dòng hỏng", extra={"carrier": self.carrier, "statement_id": statement_id,
                                                      "line_no": line_no, "error": str(e)})
        return result

    def _line(self, row: dict, statement_id: str, ingested_at: datetime) -> dict:
        if row.get("__extra__") or any(v is None for k, v in row.items() if k != "__extra__"):
            raise RowError("sai số cột")
        line: dict = {"statement_id": statement_id, "carrier": self.carrier}
        for col, name in self.columns.items():
            if name == "order_code":
                code = row[col].strip()
                if not code:
                    raise RowError("thiếu mã đơn")
                line["order_code"] = code
            else:
                line[name] = parse_money(row[col], name)
        line["raw"] = {k: v for k, v in row.items() if k != "__extra__"}
        line["ingested_at"] = ingested_at
        return line
