"""Tax codes and tax calculation (exclusive and VAT-style inclusive prices)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .money import Money


class UnknownTaxCode(KeyError):
    pass


@dataclass(frozen=True)
class TaxRate:
    code: str
    rate: Decimal
    inclusive: bool = False


RATES = {
    "STD": TaxRate("STD", Decimal("0.20")),
    "RED": TaxRate("RED", Decimal("0.05")),
    "ZERO": TaxRate("ZERO", Decimal("0")),
    "NYC": TaxRate("NYC", Decimal("0.08875")),
    "VAT": TaxRate("VAT", Decimal("0.20"), inclusive=True),
}


def lookup(code: str) -> TaxRate:
    try:
        return RATES[code]
    except KeyError:
        raise UnknownTaxCode(code) from None


def split_inclusive(gross: Money, rate: TaxRate) -> tuple[Money, Money]:
    """Split a tax-inclusive price into (net, tax)."""
    net = Money(gross.amount / (1 + rate.rate), gross.currency)
    return net, gross - net


def tax_on(net: Money, rate: TaxRate) -> Money:
    """Tax due on an amount. Inclusive rates treat the amount as already containing tax."""
    if rate.inclusive:
        return split_inclusive(net, rate)[1]
    return net * rate.rate
