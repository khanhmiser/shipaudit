"""[A] Parser bảng kê theo mã hãng."""
from app.ingest.parsers.base import ParseResult, RowError, StatementFormatError, StatementParser
from app.ingest.parsers.carrier_a import CarrierAParser
from app.ingest.parsers.carrier_b import CarrierBParser
from app.ingest.parsers.carrier_c import CarrierCParser

PARSERS: dict[str, type[StatementParser]] = {p.carrier: p for p in (CarrierAParser, CarrierBParser, CarrierCParser)}


def get_parser(carrier: str) -> StatementParser:
    try:
        return PARSERS[carrier]()
    except KeyError:
        raise ValueError(f"không có parser cho hãng {carrier!r} (có: {', '.join(PARSERS)})") from None


__all__ = ["PARSERS", "ParseResult", "RowError", "StatementFormatError", "StatementParser", "get_parser"]
