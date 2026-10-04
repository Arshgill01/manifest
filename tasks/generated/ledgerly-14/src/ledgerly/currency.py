"""Currency conversion with a fixed rate table."""

from __future__ import annotations

from decimal import Decimal

from .money import Money

# 1 unit of the first currency = rate units of the second.
RATES = {
    ("EUR", "USD"): Decimal("1.10"),
    ("GBP", "USD"): Decimal("1.25"),
    ("USD", "JPY"): Decimal("150"),
}


class NoRate(LookupError):
    pass


def rate(source: str, target: str) -> Decimal:
    if source == target:
        return Decimal(1)
    if (source, target) in RATES:
        return RATES[(source, target)]
    if (target, source) in RATES:
        return RATES[(target, source)]
    raise NoRate(f"no rate {source}->{target}")


def convert(money: Money, target: str) -> Money:
    return Money(money.amount * rate(money.currency, target), target)
