from decimal import Decimal

import pytest

from ledgerly.money import Money
from ledgerly.tax import UnknownTaxCode, lookup, split_inclusive, tax_on


def m(s):
    return Money(Decimal(s))


def test_unknown_code():
    with pytest.raises(UnknownTaxCode):
        lookup("MOON")


def test_standard_and_city_rates():
    assert tax_on(m("100.00"), lookup("STD")) == m("20.00")
    assert tax_on(m("10.00"), lookup("NYC")) == m("0.89")


def test_half_cent_tax_rounds_up():
    assert tax_on(m("0.50"), lookup("RED")) == m("0.03")


def test_split_inclusive_price():
    assert split_inclusive(m("120.00"), lookup("VAT")) == (m("100.00"), m("20.00"))
    assert split_inclusive(m("10.00"), lookup("VAT")) == (m("8.33"), m("1.67"))


def test_inclusive_tax_on_gross():
    assert tax_on(m("60.00"), lookup("VAT")) == m("10.00")
