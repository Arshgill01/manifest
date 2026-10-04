from decimal import Decimal

import pytest

from ledgerly.money import CurrencyMismatch, Money, allocate


def test_amounts_round_half_up_to_cents():
    assert Money(Decimal("2.345")).amount == Decimal("2.35")
    assert Money(Decimal("2.344")).amount == Decimal("2.34")
    assert Money(Decimal("-2.345")).amount == Decimal("-2.35")


def test_float_input_is_exact():
    assert Money(0.1) + Money(0.2) == Money(Decimal("0.30"))


def test_add_and_subtract():
    assert Money(Decimal("10.00")) - Money(Decimal("3.25")) == Money(Decimal("6.75"))
    assert Money(Decimal("1.10")) + Money(Decimal("2.20")) == Money(Decimal("3.30"))


def test_cannot_mix_currencies():
    with pytest.raises(CurrencyMismatch):
        Money(Decimal("1"), "USD") + Money(Decimal("1"), "EUR")
    with pytest.raises(ValueError):
        Money(Decimal("1"), "usd")


def test_multiply_rounds_result():
    assert Money(Decimal("19.99")) * 3 == Money(Decimal("59.97"))
    assert Money(Decimal("0.10")) * Decimal("0.333") == Money(Decimal("0.03"))
    assert str(Money(Decimal("5"))) == "5.00 USD"


def test_allocate_rejects_bad_input():
    with pytest.raises(ValueError):
        allocate(Money(Decimal("10.00")), [0, 0])
    with pytest.raises(ValueError):
        allocate(Money(Decimal("-1.00")), [1, 1])
