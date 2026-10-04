"""Reorder points and suggested purchase quantities."""

from __future__ import annotations

from datetime import date, timedelta

from .catalog import Product
from .reservations import ReservationBook


def position(product: Product, book: ReservationBook, incoming: int = 0) -> int:
    """Inventory position: available now plus what is already on order."""
    return book.available(product.sku) + incoming


def needs_reorder(product: Product, pos: int) -> bool:
    return pos <= product.reorder_point


def round_to_pack(qty: int, pack: int) -> int:
    """Smallest multiple of `pack` that is >= qty."""
    return (qty + pack - 1) // pack * pack


def suggested_order(product: Product, pos: int) -> int:
    """Order enough to get back to reorder point + reorder qty, in whole packs."""
    if not needs_reorder(product, pos):
        return 0
    shortfall = product.reorder_point + product.reorder_qty - pos
    return round_to_pack(shortfall, product.pack_size)


def expected_arrival(product: Product, ordered_on: date) -> date:
    return ordered_on + timedelta(days=product.lead_time_days)
