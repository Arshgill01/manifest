from datetime import datetime

from stockroom.catalog import Catalog, Product
from stockroom.inventory import Inventory
from stockroom.reservations import ReservationBook

T0 = datetime(2026, 3, 2, 9, 0)


def make_catalog():
    return Catalog([
        Product("BOLT-M6", "M6 bolt", pack_size=100, reorder_point=500, reorder_qty=1000, lead_time_days=5),
        Product("NUT-M6", "M6 nut", pack_size=50, reorder_point=200, reorder_qty=400, lead_time_days=3),
        Product("WASHER", "Washer", pack_size=1, reorder_point=10, reorder_qty=20, lead_time_days=10),
    ])


def make_book():
    inv = Inventory(make_catalog())
    inv.receive("BOLT-M6", 300, "MAIN")
    inv.receive("BOLT-M6", 200, "STORE")
    inv.receive("NUT-M6", 100, "MAIN")
    return ReservationBook(inv)
