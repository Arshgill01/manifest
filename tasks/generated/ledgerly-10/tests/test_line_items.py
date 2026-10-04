from decimal import Decimal

import pytest

from ledgerly.line_items import LineItem
from ledgerly.money import Money
from ledgerly.tax import UnknownTaxCode


def m(s):
    return Money(Decimal(s))


def test_gross_and_volume_discount():
    item = LineItem("BOLT", 10, m("2.00"))
    assert item.gross() == m("20.00")
    assert item.discount() == m("1.00")
    assert item.net() == m("19.00")
    assert item.total() == m("22.80")


def test_negotiated_discount_beats_volume():
    item = LineItem("BOLT", 10, m("2.00"), discount_percent=Decimal("12"))
    assert item.net() == m("17.60")


def test_validation():
    with pytest.raises(ValueError):
        LineItem("BOLT", 0, m("2.00"))
    with pytest.raises(UnknownTaxCode):
        LineItem("BOLT", 1, m("2.00"), tax_code="MOON")


def test_inclusive_line():
    item = LineItem("TEA", 2, m("6.00"), "VAT")
    assert item.tax() == m("2.00")
    assert item.total() == m("12.00")


def test_half_cent_line_tax():
    item = LineItem("PEN", 1, m("0.50"), "RED")
    assert item.tax() == m("0.03")
    assert item.total() == m("0.53")
