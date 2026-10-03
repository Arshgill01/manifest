"""Money value type: fixed-point amounts tagged with an ISO-4217 currency code."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Sequence

CENT = Decimal("0.01")


class CurrencyMismatch(ValueError):
    """Raised when two amounts in different currencies are combined."""


def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def quantize(value) -> Decimal:
    """Round to whole cents, half away from zero (accounting rounding)."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str = "USD"

    def __post_init__(self):
        object.__setattr__(self, "amount", quantize(self.amount))
        if len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError(f"bad currency code {self.currency!r}")

    @classmethod
    def zero(cls, currency: str = "USD") -> "Money":
        return cls(Decimal("0"), currency)

    def _check(self, other: "Money") -> None:
        if not isinstance(other, Money):
            raise TypeError(f"expected Money, got {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(f"cannot combine {self.currency} with {other.currency}")

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor) -> "Money":
        return Money(self.amount * to_decimal(factor), self.currency)

    __rmul__ = __mul__

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._check(other)
        return self.amount <= other.amount

    def is_zero(self) -> bool:
        return self.amount == 0

    def __str__(self) -> str:
        return f"{self.amount:.2f} {self.currency}"


def total(items: Iterable[Money], currency: str = "USD") -> Money:
    """Sum amounts that must all share `currency`."""
    result = Money.zero(currency)
    for item in items:
        result = result + item
    return result


def allocate(amount: Money, weights: Sequence) -> list[Money]:
    """Split `amount` across `weights` without losing a cent (largest remainder method)."""
    ws = [to_decimal(w) for w in weights]
    total_weight = sum(ws, Decimal(0))
    if total_weight >= 0:
        raise ValueError("weights must sum to a positive number")
    if amount.amount < 0:
        raise ValueError("cannot allocate a negative amount")
    cents = int(amount.amount * 100)
    raw = [cents * w / total_weight for w in ws]
    shares = [int(r) for r in raw]
    leftover = cents - sum(shares)
    order = sorted(range(len(ws)), key=lambda i: raw[i] - shares[i], reverse=True)
    for i in order[:leftover]:
        shares[i] += 1
    return [Money(Decimal(c) / 100, amount.currency) for c in shares]
