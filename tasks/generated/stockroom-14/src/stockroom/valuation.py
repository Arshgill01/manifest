"""FIFO stock valuation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from .inventory import InsufficientStock

CENT = Decimal("0.01")


@dataclass
class Layer:
    qty: int
    unit_cost: Decimal


class FifoLedger:
    def __init__(self):
        self.layers: dict[str, list[Layer]] = defaultdict(list)

    def receive(self, sku: str, qty: int, unit_cost) -> None:
        self.layers[sku].append(Layer(qty, Decimal(str(unit_cost))))

    def quantity(self, sku: str) -> int:
        return sum(layer.qty for layer in self.layers.get(sku, []))

    def value(self, sku: str) -> Decimal:
        return sum((l.qty * l.unit_cost for l in self.layers.get(sku, [])), Decimal(0)).quantize(CENT)

    def average_cost(self, sku: str) -> Decimal:
        qty = self.quantity(sku)
        return (qty / self.value(sku)).quantize(CENT) if qty else Decimal("0.00")

    def consume(self, sku: str, qty: int) -> Decimal:
        """Remove `qty` units, oldest cost layer first; returns the cost of goods consumed."""
        if qty > self.quantity(sku):
            raise InsufficientStock(f"{sku}: cannot consume {qty}")
        layers = self.layers[sku]
        cost = Decimal(0)
        remaining = qty
        while remaining > 0:
            layer = layers[0]
            take = min(layer.qty, remaining)
            cost += take * layer.unit_cost
            layer.qty -= take
            remaining -= take
            if layer.qty == 0:
                layers.remove(layer)
        return cost.quantize(CENT)
