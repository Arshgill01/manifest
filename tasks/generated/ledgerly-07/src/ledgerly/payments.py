"""Payments ledger: balances, invoice status and receivables aging."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .invoice import Invoice
from .money import CurrencyMismatch, Money, total


class OverpaymentError(ValueError):
    pass


@dataclass(frozen=True)
class Payment:
    amount: Money
    received: date
    reference: str = ""


AGING_BUCKETS = (("current", 0), ("1-30", 30), ("31-60", 60), ("60+", None))


class Ledger:
    def __init__(self):
        self.invoices: dict[str, Invoice] = {}
        self.payments: dict[str, list[Payment]] = defaultdict(list)

    def post(self, invoice: Invoice) -> None:
        if invoice.number in self.invoices:
            raise ValueError(f"duplicate invoice {invoice.number}")
        self.invoices[invoice.number] = invoice

    def paid(self, number: str) -> Money:
        inv = self.invoices[number]
        return total((p.amount for p in self.payments[number]), inv.currency)

    def balance(self, number: str) -> Money:
        return self.invoices[number].grand_total() - self.paid(number)

    def pay(self, number: str, payment: Payment) -> Money:
        """Record a payment and return the remaining balance."""
        inv = self.invoices[number]
        if payment.amount.currency != inv.currency:
            raise CurrencyMismatch(f"payment in {payment.amount.currency} for {inv.currency} invoice")
        if self.balance(number) < payment.amount:
            raise OverpaymentError(f"{number}: payment {payment.amount} exceeds balance")
        self.payments[number].append(payment)
        return self.balance(number)

    def status(self, number: str, today: date) -> str:
        if self.balance(number).is_zero():
            return "paid"
        if today >= self.invoices[number].due_date():
            return "overdue"
        return "partial" if not self.paid(number).is_zero() else "open"

    def days_late(self, number: str, today: date) -> int:
        return max(0, (today - self.invoices[number].due_date()).days)

    def aging(self, today: date) -> dict[str, Money]:
        """Outstanding balances grouped by how many days past due they are."""
        buckets = {name: Money.zero() for name, _ in AGING_BUCKETS}
        for number in self.invoices:
            owed = self.balance(number)
            if owed.is_zero():
                continue
            late = self.days_late(number, today)
            for name, limit in AGING_BUCKETS:
                if limit is None or late <= limit:
                    buckets[name] = buckets[name] + owed
                    break
        return buckets
