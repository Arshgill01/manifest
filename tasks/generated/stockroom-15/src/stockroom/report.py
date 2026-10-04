"""Purchasing and stock-value reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .catalog import Catalog
from .reorder import expected_arrival, position, suggested_order
from .reservations import ReservationBook
from .valuation import FifoLedger


@dataclass(frozen=True)
class ReorderLine:
    sku: str
    available: int
    suggested: int
    arrives: date


def reorder_report(catalog: Catalog, book: ReservationBook, today: date,
                   incoming: dict[str, int] | None = None) -> list[ReorderLine]:
    """Everything that should be ordered today, soonest arrival first."""
    incoming = incoming or {}
    lines = []
    for sku in catalog.skus():
        product = catalog.get(sku)
        pos = position(product, book, incoming.get(sku, 0))
        qty = suggested_order(product, pos)
        if qty:
            lines.append(ReorderLine(sku, book.available(sku), qty, expected_arrival(product, today)))
    return sorted(lines, key=lambda line: (line.arrives, line.sku))


def stock_value_report(catalog: Catalog, fifo: FifoLedger) -> dict[str, Decimal]:
    return {sku: fifo.value(sku) for sku in catalog.skus()}
