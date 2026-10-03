"""Invoices: lines, invoice-level discounts, tax breakdown and totals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .discounts import coupon_discount, spread
from .line_items import LineItem
from .money import CurrencyMismatch, Money, total
from .tax import lookup, tax_on


@dataclass
class Invoice:
    number: str
    customer: str
    issued: date
    currency: str = "USD"
    terms_days: int = 30
    lines: list[LineItem] = field(default_factory=list)
    coupon: str | None = None

    def add(self, item: LineItem) -> "Invoice":
        if item.unit_price.currency != self.currency:
            raise CurrencyMismatch(f"line {item.sku} is in {item.unit_price.currency}")
        self.lines.append(item)
        return self

    def due_date(self) -> date:
        return self.issued + timedelta(days=self.terms_days)

    def subtotal(self) -> Money:
        return total((line.net() for line in self.lines), self.currency)

    def invoice_discount(self) -> Money:
        if not self.coupon or not self.lines:
            return Money.zero(self.currency)
        return coupon_discount(self.subtotal(), self.coupon)

    def line_discounts(self) -> list[Money]:
        """The invoice-level discount, spread across lines."""
        discount = self.invoice_discount()
        if discount.is_zero():
            return [Money.zero(self.currency) for _ in self.lines]
        return spread(discount, [line.net() for line in self.lines])

    def tax_breakdown(self) -> dict[str, Money]:
        """Tax per tax code, computed on each line's net after its share of the invoice discount."""
        breakdown: dict[str, Money] = {}
        for line, share in zip(self.lines, self.line_discounts()):
            tax = tax_on(line.net() - share, lookup(line.tax_code))
            breakdown[line.tax_code] = breakdown.get(line.tax_code, Money.zero(self.currency)) + tax
        return breakdown

    def tax_total(self) -> Money:
        return total(self.tax_breakdown().values(), self.currency)

    def exclusive_tax_total(self) -> Money:
        return total(
            (t for code, t in self.tax_breakdown().items() if not lookup(code).inclusive),
            self.currency,
        )

    def grand_total(self) -> Money:
        return self.subtotal() - self.invoice_discount() + self.exclusive_tax_total()

    def summary(self) -> dict[str, str]:
        return {
            "number": self.number,
            "customer": self.customer,
            "due": self.due_date().isoformat(),
            "subtotal": str(self.subtotal()),
            "discount": str(self.invoice_discount()),
            "tax": str(self.tax_total()),
            "total": str(self.grand_total()),
        }
