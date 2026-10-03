from datetime import date
from decimal import Decimal

import pytest

from ledgerly.invoice import Invoice
from ledgerly.line_items import LineItem
from ledgerly.money import CurrencyMismatch, Money


def m(s, cur="USD"):
    return Money(Decimal(s), cur)


def make_invoice(coupon=None):
    inv = Invoice("INV-1", "Acme", date(2026, 1, 1), coupon=coupon)
    inv.add(LineItem("WIDGET", 4, m("12.50"), "STD"))
    inv.add(LineItem("GADGET", 10, m("3.00"), "RED"))
    inv.add(LineItem("BOOK", 1, m("21.50"), "ZERO"))
    return inv


def test_subtotal_and_due_date():
    inv = make_invoice()
    assert inv.subtotal() == m("100.00")
    assert inv.due_date() == date(2026, 1, 31)


def test_tax_breakdown_without_coupon():
    assert make_invoice().tax_breakdown() == {"STD": m("10.00"), "RED": m("1.43"), "ZERO": m("0.00")}


def test_grand_total_without_coupon():
    assert make_invoice().grand_total() == m("111.43")


def test_percent_coupon_is_spread_before_tax():
    inv = make_invoice("WELCOME10")
    assert inv.invoice_discount() == m("10.00")
    assert inv.line_discounts() == [m("5.00"), m("2.85"), m("2.15")]
    assert inv.tax_total() == m("10.28")
    assert inv.grand_total() == m("100.28")


def test_flat_coupon_spread_keeps_every_cent():
    inv = make_invoice("FLAT5")
    assert inv.line_discounts() == [m("2.50"), m("1.43"), m("1.07")]
    assert inv.grand_total() == m("105.85")


def test_coupon_cannot_exceed_subtotal():
    inv = Invoice("INV-2", "Acme", date(2026, 1, 1), coupon="BIGSPENDER")
    inv.add(LineItem("BOOK", 1, m("30.00"), "ZERO"))
    assert inv.grand_total() == m("0.00")


def test_inclusive_tax_not_added_twice():
    inv = Invoice("INV-3", "Acme", date(2026, 1, 1))
    inv.add(LineItem("TEA", 2, m("6.00"), "VAT"))
    inv.add(LineItem("MUG", 1, m("10.00"), "STD"))
    assert inv.tax_total() == m("4.00")
    assert inv.grand_total() == m("24.00")


def test_currency_and_summary():
    inv = make_invoice()
    with pytest.raises(CurrencyMismatch):
        inv.add(LineItem("EURO", 1, m("1.00", "EUR")))
    assert inv.summary()["total"] == "111.43 USD"
    assert inv.summary()["due"] == "2026-01-31"
