"""Volume tiers, coupons and invoice-level discount spreading."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .money import Money, allocate, to_decimal


@dataclass(frozen=True)
class Tier:
    min_qty: int
    percent: Decimal


# Highest tier first.
VOLUME_TIERS = (
    Tier(100, Decimal("15")),
    Tier(50, Decimal("10")),
    Tier(10, Decimal("5")),
)

COUPONS = {
    "WELCOME10": ("percent", Decimal("10")),
    "FLAT5": ("fixed", Decimal("5.00")),
    "BIGSPENDER": ("fixed", Decimal("50.00")),
}


class InvalidCoupon(ValueError):
    pass


def volume_percent(quantity: int, tiers=VOLUME_TIERS) -> Decimal:
    for tier in tiers:
        if quantity >= tier.min_qty:
            return tier.percent
    return Decimal("0")


def percent_off(amount: Money, percent) -> Money:
    pct = to_decimal(percent)
    if not 0 < pct <= 100:
        raise ValueError(f"discount percent out of range: {pct}")
    return amount * (pct / 100)


def coupon_discount(subtotal: Money, code: str) -> Money:
    """Discount a coupon gives on `subtotal`; fixed coupons never exceed the subtotal."""
    try:
        kind, value = COUPONS[code.upper()]
    except KeyError:
        raise InvalidCoupon(code) from None
    if kind == "percent":
        return percent_off(subtotal, value)
    return min(Money(value, subtotal.currency), subtotal)


def spread(discount: Money, line_nets: list[Money]) -> list[Money]:
    """Spread an invoice-level discount over lines in proportion to their net amounts."""
    if not line_nets:
        return []
    return allocate(discount, [n.amount for n in line_nets])
