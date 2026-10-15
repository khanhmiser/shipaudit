"""[B] Tiền: số nguyên VNĐ. Không dùng float."""
from decimal import ROUND_HALF_UP, Decimal


def to_vnd(value) -> int:
    """Làm tròn về số nguyên VNĐ (half up)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
