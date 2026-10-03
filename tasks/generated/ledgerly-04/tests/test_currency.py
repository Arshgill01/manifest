from decimal import Decimal

import pytest

from ledgerly.currency import NoRate, convert
from ledgerly.money import Money


def test_direct_rate():
    assert convert(Money(Decimal("10.00"), "EUR"), "USD") == Money(Decimal("11.00"), "USD")
    assert convert(Money(Decimal("2.00"), "USD"), "JPY") == Money(Decimal("300.00"), "JPY")


def test_inverse_rate():
    assert convert(Money(Decimal("11.00"), "USD"), "EUR") == Money(Decimal("10.00"), "EUR")
    assert convert(Money(Decimal("1500"), "JPY"), "USD") == Money(Decimal("10.00"), "USD")


def test_same_currency_is_identity():
    assert convert(Money(Decimal("3.21"), "GBP"), "GBP") == Money(Decimal("3.21"), "GBP")


def test_missing_rate():
    with pytest.raises(NoRate):
        convert(Money(Decimal("1.00"), "EUR"), "JPY")
