"""Parser 3 hãng trên contracts/samples: đúng từng giá trị, dòng hỏng bị bỏ qua, sai tiêu đề là lỗi cấp file."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.ingest.parsers import PARSERS, StatementFormatError, get_parser

SAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "samples"
AT = datetime(2026, 10, 22, 2, 0, tzinfo=timezone.utc)


def _sample(carrier: str) -> bytes:
    return (SAMPLES / f"statement_{carrier}.csv").read_bytes()


def _money(line: dict) -> dict:
    return {k: v for k, v in line.items() if k not in ("statement_id", "carrier", "order_code", "raw", "ingested_at")}


def test_carrier_a_sample_every_value():
    lines = get_parser("carrier_a").parse(_sample("carrier_a"), "STM-A-T", ingested_at=AT)
    assert [line["order_code"] for line in lines] == ["A-0001", "A-0002", "A-0003", "A-0004"]
    assert [_money(line) for line in lines] == [
        {"cod_collected": 350000, "shipping_fee": 32000, "insurance_fee": 3500, "return_shipping_fee": 0,
         "transfer_fee": 1650, "net_paid": 312850},
        {"cod_collected": 0, "shipping_fee": 28000, "insurance_fee": 0, "return_shipping_fee": 0,
         "transfer_fee": 0, "net_paid": -28000},
        {"cod_collected": 520000, "shipping_fee": 41000, "insurance_fee": 5200, "return_shipping_fee": 0,
         "transfer_fee": 1650, "net_paid": 472150},
        {"cod_collected": 180000, "shipping_fee": 25000, "insurance_fee": 0, "return_shipping_fee": 25000,
         "transfer_fee": 1650, "net_paid": 128350},
    ]
    first = lines[0]
    assert first["statement_id"] == "STM-A-T" and first["carrier"] == "carrier_a" and first["ingested_at"] == AT
    assert first["raw"] == {"order_code": "A-0001", "cod_amount": "350000", "ship_fee": "32000", "insurance": "3500",
                            "return_fee": "0", "transfer_fee": "1650", "net_paid": "312850"}


def test_carrier_b_sample_every_value():
    lines = get_parser("carrier_b").parse(_sample("carrier_b"), "STM-B-T", ingested_at=AT)
    assert [(line["order_code"], _money(line)) for line in lines] == [
        ("B-0001", {"cod_collected": 410000, "shipping_fee": 36000, "return_shipping_fee": 0, "storage_fee": 0,
                    "net_paid": 374000}),
        ("B-0002", {"cod_collected": 275000, "shipping_fee": 30000, "return_shipping_fee": 0, "storage_fee": 12000,
                    "net_paid": 233000}),
        ("B-0003", {"cod_collected": 0, "shipping_fee": 33000, "return_shipping_fee": 33000, "storage_fee": 0,
                    "net_paid": -66000}),
        ("B-0004", {"cod_collected": 640000, "shipping_fee": 47000, "return_shipping_fee": 0, "storage_fee": 0,
                    "net_paid": 593000}),
    ]
    assert lines[1]["raw"]["phi_luu_kho"] == "12000"


def test_carrier_c_sample_every_value_note_in_raw():
    lines = get_parser("carrier_c").parse(_sample("carrier_c"), "STM-C-T", ingested_at=AT)
    assert [(line["order_code"], _money(line)) for line in lines] == [
        ("C-0001", {"cod_collected": 300000, "shipping_fee": 29500, "net_paid": 270500}),
        ("C-0002", {"cod_collected": 455000, "shipping_fee": 38000, "net_paid": 412000}),
        ("C-0003", {"cod_collected": 120000, "shipping_fee": 24000, "net_paid": 96000}),
        ("C-0004", {"cod_collected": 0, "shipping_fee": 27000, "net_paid": -27000}),
    ]
    assert [line["raw"]["note"] for line in lines] == ["", "doi dia chi", "hang loi", "hoan"]
    assert "note" not in lines[1]


@pytest.mark.parametrize("carrier", list(PARSERS))
def test_money_is_int_never_float(carrier):
    for line in get_parser(carrier).parse(_sample(carrier), "S"):
        assert all(type(v) is int for v in _money(line).values())


def test_broken_rows_skipped_and_reported():
    raw = (
        "order_code,cod_amount,ship_fee,insurance,return_fee,transfer_fee,net_paid\n"
        "A-1,100000,20000,0,0,1650,78350\n"
        "A-2,abc,20000,0,0,1650,78350\n"        # tiền không phải số
        "A-3,100000,20000.5,0,0,1650,78350\n"   # số lẻ
        ",100000,20000,0,0,1650,78350\n"        # thiếu mã đơn
        "A-5,100000,20000,0,0,1650\n"           # thiếu cột
        "A-6,100000,20000,0,0,1650,78350,9\n"   # thừa cột
        "A-7,100000,20000,0,0,1650,\n"          # net_paid trống
        "\n"
        "A-8,100000,20000,,,1650,78350\n"       # phí trống coi là 0
    ).encode()
    report = get_parser("carrier_a").parse_report(raw, "S")
    assert [line["order_code"] for line in report.lines] == ["A-1", "A-8"]
    assert report.lines[1]["insurance_fee"] == 0 and report.lines[1]["return_shipping_fee"] == 0
    assert len(report.errors) == 6
    assert report.errors[0].startswith("dòng 3:")


def test_wrong_header_is_file_error():
    raw = b"order_code,cod,ship_fee,insurance,return_fee,transfer_fee,net_paid\nA-1,1,1,0,0,0,1\n"
    with pytest.raises(StatementFormatError, match="thiếu"):
        get_parser("carrier_a").parse(raw, "S")


def test_wrong_delimiter_is_file_error():
    # File của hãng B (dấu chấm phẩy) gửi nhầm vào parser hãng A.
    with pytest.raises(StatementFormatError):
        get_parser("carrier_a").parse(_sample("carrier_b"), "S")


def test_not_utf8_is_file_error():
    with pytest.raises(StatementFormatError, match="UTF-8"):
        get_parser("carrier_c").parse("tracking,cod,total_fee,note,net\nC-1,1,1,hàng,0\n".encode("latin-1"), "S")


def test_utf8_bom_and_header_spaces_accepted():
    raw = "﻿ma_don ; thu_ho;cuoc_van_chuyen;phi_hoan;phi_luu_kho;thuc_tra\nB-1;1000;100;0;0;900\n".encode()
    assert get_parser("carrier_b").parse(raw, "S")[0]["net_paid"] == 900


def test_unknown_carrier():
    with pytest.raises(ValueError, match="không có parser"):
        get_parser("carrier_x")
