"""Kiểm tra công thức đối soát đã chốt (contracts.interfaces.Breakdown)."""
from contracts.interfaces import Breakdown


def test_basic_cod_order():
    b = Breakdown(cod_collected=350_000, shipping_fee=32_000, insurance_fee=3_500, transfer_fee=1_650)
    assert b.expected_amount == 312_850


def test_return_order_has_negative_amount():
    b = Breakdown(shipping_fee=33_000, return_shipping_fee=33_000)
    assert b.expected_amount == -66_000


def test_all_terms():
    b = Breakdown(
        cod_collected=500_000, prepaid_by_shop=10_000, return_fee_paid_by_shop=5_000, promotion=2_000,
        shipping_fee=30_000, insurance_fee=3_000, return_shipping_fee=0, storage_fee=4_000,
        address_change_fee=1_000, inspection_fee=2_000, transfer_fee=1_650,
    )
    assert b.expected_amount == 517_000 - 41_650
