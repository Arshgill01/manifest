from datetime import date
from decimal import Decimal

from stockroom.report import ReorderLine, reorder_report, stock_value_report
from stockroom.valuation import FifoLedger

from .helpers import T0, make_book, make_catalog

TODAY = date(2026, 3, 2)


def test_reorder_report_sorted_by_arrival():
    book = make_book()
    assert reorder_report(book.inventory.catalog, book, TODAY) == [
        ReorderLine("NUT-M6", 100, 500, date(2026, 3, 5)),
        ReorderLine("BOLT-M6", 500, 1000, date(2026, 3, 7)),
        ReorderLine("WASHER", 0, 30, date(2026, 3, 12)),
    ]


def test_incoming_stock_suppresses_orders():
    book = make_book()
    skus = [line.sku for line in reorder_report(book.inventory.catalog, book, TODAY, {"BOLT-M6": 1})]
    assert skus == ["NUT-M6", "WASHER"]


def test_reservations_count_against_position():
    book = make_book()
    book.reserve("NUT-M6", 50, T0)
    nut = [l for l in reorder_report(book.inventory.catalog, book, TODAY) if l.sku == "NUT-M6"][0]
    assert (nut.available, nut.suggested) == (50, 550)


def test_stock_value_report():
    fifo = FifoLedger()
    fifo.receive("BOLT-M6", 100, "0.10")
    fifo.receive("NUT-M6", 50, "0.20")
    fifo.receive("NUT-M6", 50, "0.30")
    fifo.consume("NUT-M6", 60)
    assert stock_value_report(make_catalog(), fifo) == {
        "BOLT-M6": Decimal("10.00"), "NUT-M6": Decimal("12.00"), "WASHER": Decimal("0.00"),
    }
