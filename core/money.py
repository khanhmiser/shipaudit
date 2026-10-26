"""[B] Tiền: số nguyên VNĐ. Không dùng float."""
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

ROUNDING_MODES = {"half_up": ROUND_HALF_UP, "half_even": ROUND_HALF_EVEN}


def to_vnd(value) -> int:
    """Làm tròn về số nguyên VNĐ (half up)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bp(amount: int, rate_bp: int, unit: int = 1, mode: str = "half_up") -> int:
    """amount × rate_bp / 10000 (1 bp = 0,01%), làm tròn về bội số của `unit` VNĐ.

    Mặc định làm tròn half up về 1đ. Hãng có thể quy định làm tròn khác (vd 100đ, half_even)."""
    value = Decimal(amount) * Decimal(rate_bp) / Decimal(10_000)
    return int((value / Decimal(unit)).quantize(Decimal("1"), rounding=ROUNDING_MODES[mode])) * unit
