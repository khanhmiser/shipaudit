"""[B] compute_expected(order, line, rule) -> Breakdown, đúng công thức đối soát.

Công thức nằm ở contracts.interfaces.Breakdown.expected_amount.
Việc cần làm: tính từng khoản (cước theo khối lượng quy đổi và vùng, phụ phí, hoàn/trả/hàng lỗi...)
và điền vào Breakdown. Golden test: tests/core/.
"""
from contracts.interfaces import Breakdown


def compute_expected(order: dict, line: dict | None, rule: dict) -> Breakdown:
    # TODO(B): cài thật theo quy tắc từng hãng.
    raise NotImplementedError
