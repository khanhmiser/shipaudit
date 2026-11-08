"""[A] Parser Carrier A. Định dạng mẫu: CSV dấu phẩy: order_code,cod_amount,ship_fee,insurance,return_fee,transfer_fee,net_paid.
Mẫu thử: contracts/samples/statement_carrier_a.csv
"""
from app.ingest.parsers.base import StatementParser


class CarrierAParser(StatementParser):
    carrier = "carrier_a"
    delimiter = ","
    columns = {
        "order_code": "order_code",
        "cod_amount": "cod_collected",
        "ship_fee": "shipping_fee",
        "insurance": "insurance_fee",
        "return_fee": "return_shipping_fee",
        "transfer_fee": "transfer_fee",
        "net_paid": "net_paid",
    }
