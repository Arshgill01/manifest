"""Invoice line items."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .discounts import percent_off, volume_percent
from .money import Money
from .tax import lookup, tax_on


@dataclass
class LineItem:
    sku: str
    quantity: int
    unit_price: Money
    tax_code: str = "STD"
    discount_percent: Decimal = Decimal("0")

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError(f"{self.sku}: quantity must be positive")
        lookup(self.tax_code)  # fail fast on unknown codes

    def gross(self) -> Money:
        return self.unit_price * self.quantity

    def effective_discount_percent(self) -> Decimal:
        """The better of the negotiated discount and the volume tier."""
        return max(Decimal(self.discount_percent), volume_percent(self.quantity))

    def discount(self) -> Money:
        return percent_off(self.gross(), self.effective_discount_percent())

    def net(self) -> Money:
        return self.gross() - self.discount()

    def tax(self) -> Money:
        return tax_on(self.net(), lookup(self.tax_code))

    def total(self) -> Money:
        if lookup(self.tax_code).inclusive:
            return self.net()
        return self.net() + self.tax()
