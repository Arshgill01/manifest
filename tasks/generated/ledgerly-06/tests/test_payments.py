from datetime import date
from decimal import Decimal

import pytest

from ledgerly.invoice import Invoice
from ledgerly.line_items import LineItem
from ledgerly.money import CurrencyMismatch, Money
from ledgerly.payments import Ledger, OverpaymentError, Payment


def m(s, cur="USD"):
    return Money(Decimal(s), cur)


def simple_invoice(number, issued, amount):
    inv = Invoice(number, "Acme", issued)
    inv.add(LineItem("ITEM", 1, m(amount), "ZERO"))
    return inv


def make_ledger():
    ledger = Ledger()
    inv = Invoice("INV-1", "Acme", date(2026, 1, 1))
    inv.add(LineItem("WIDGET", 4, m("12.50"), "STD"))
    inv.add(LineItem("GADGET", 10, m("3.00"), "RED"))
    inv.add(LineItem("BOOK", 1, m("21.50"), "ZERO"))
    ledger.post(inv)
    return ledger


def test_partial_then_full_payment():
    ledger = make_ledger()
    assert ledger.pay("INV-1", Payment(m("50.00"), date(2026, 1, 10))) == m("61.43")
    assert ledger.status("INV-1", date(2026, 1, 15)) == "partial"
    assert ledger.pay("INV-1", Payment(m("61.43"), date(2026, 1, 20))) == m("0.00")
    assert ledger.status("INV-1", date(2026, 3, 1)) == "paid"


def test_status_on_and_after_due_date():
    ledger = make_ledger()
    assert ledger.status("INV-1", date(2026, 1, 31)) == "open"
    assert ledger.status("INV-1", date(2026, 2, 1)) == "overdue"
    assert ledger.days_late("INV-1", date(2026, 1, 10)) == 0


def test_overpayment_rejected():
    ledger = make_ledger()
    with pytest.raises(OverpaymentError):
        ledger.pay("INV-1", Payment(m("200.00"), date(2026, 1, 10)))


def test_payment_currency_must_match():
    ledger = make_ledger()
    with pytest.raises(CurrencyMismatch):
        ledger.pay("INV-1", Payment(m("5.00", "EUR"), date(2026, 1, 10)))


def test_duplicate_invoice_rejected():
    ledger = make_ledger()
    with pytest.raises(ValueError):
        ledger.post(simple_invoice("INV-1", date(2026, 1, 1), "1.00"))


def test_aging_buckets():
    ledger = make_ledger()
    ledger.post(simple_invoice("B", date(2025, 12, 1), "100.00"))   # 31 days late
    ledger.post(simple_invoice("C", date(2025, 10, 1), "40.00"))    # 92 days late
    ledger.post(simple_invoice("D", date(2025, 12, 2), "25.00"))    # exactly 30 days late
    assert ledger.aging(date(2026, 1, 31)) == {
        "current": m("111.43"),
        "1-30": m("25.00"),
        "31-60": m("100.00"),
        "60+": m("40.00"),
    }
