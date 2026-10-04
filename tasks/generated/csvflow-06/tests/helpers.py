from csvflow.schema import Column, Schema

SALES = """Order ID, Region ,Amount,Shipped On,Express
A1,north,120.50,2026-01-03,yes
A2,south,80.00,2026-01-04,no
A3,north,99.50,2026-01-05,no
A4,east,,2026-01-05,yes
A5,south,abc,2026-01-06,no
A2,south,80.00,2026-01-04,no
"""

SCHEMA = Schema((
    Column("order_id"),
    Column("region"),
    Column("amount", "float"),
    Column("shipped_on", "date"),
    Column("express", "bool", required=False, default=False),
))
