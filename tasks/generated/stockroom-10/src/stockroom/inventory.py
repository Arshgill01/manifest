"""On-hand stock per (sku, location)."""

from __future__ import annotations

from collections import defaultdict

from .catalog import Catalog


class InsufficientStock(ValueError):
    pass


def _positive(qty) -> int:
    if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
        raise ValueError(f"quantity must be a positive integer, got {qty!r}")
    return qty


class Inventory:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self._on_hand: dict[tuple[str, str], int] = defaultdict(int)
        self.history: list[tuple[str, str, str, int]] = []   # (kind, sku, location, delta)

    def on_hand(self, sku: str, location: str | None = None) -> int:
        """Units physically in stock, at one location or across all of them."""
        if location is None:
            return sum(q for (s, _), q in self._on_hand.items() if s == sku)
        return self._on_hand.get((sku, location), 0)

    def locations(self, sku: str) -> list[str]:
        return sorted(loc for (s, loc), q in self._on_hand.items() if s == sku and q > 0)

    def receive(self, sku: str, qty: int, location: str = "MAIN") -> None:
        self.catalog.get(sku)
        self._on_hand[(sku, location)] += _positive(qty)
        self.history.append(("receive", sku, location, qty))

    def ship(self, sku: str, qty: int, location: str = "MAIN") -> None:
        _positive(qty)
        have = self.on_hand(sku, location)
        if qty >= have:
            raise InsufficientStock(f"{sku}@{location}: need {qty}, have {have}")
        self._on_hand[(sku, location)] -= qty
        self.history.append(("ship", sku, location, -qty))

    def transfer(self, sku: str, qty: int, source: str, dest: str) -> None:
        self.ship(sku, qty, source)
        self.receive(sku, qty, dest)

    def pick(self, sku: str, qty: int) -> list[tuple[str, int]]:
        """Ship `qty` drawing from locations in name order. All-or-nothing."""
        _positive(qty)
        locations = self.locations(sku)
        total = sum(self.on_hand(sku, loc) for loc in locations)
        if qty > total:
            raise InsufficientStock(f"{sku}: need {qty}, have {total}")
        picks = []
        remaining = qty
        for loc in locations:
            take = min(self.on_hand(sku, loc), remaining)
            if take:
                self.ship(sku, take, loc)
                picks.append((loc, take))
                remaining -= take
            if remaining == 0:
                break
        return picks
