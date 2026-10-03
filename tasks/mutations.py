"""Injected root-cause bugs, one per task.

Each mutation is a single-site edit (occasionally two lines of the same statement) to a clean
template package. `gen.py` applies it, records which tests fail, and *verifies* the claimed bug
shapes mechanically, so a label like "regression-trap" is a checked property, not a hope:

- deep-call-chain     no failing test lives in the root module's own test file
- one-root-many       3-8 tests fail from the single defect
- regression-trap     `trap` (the tempting local fix) makes an originally failing test pass AND
                      breaks a test that was passing
- misleading-surface  every crash surfaces outside the root-cause function (callee defect, caller blows up)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Edit:
    file: str      # relative to the task root, e.g. "src/ledgerly/money.py"
    search: str
    replace: str


@dataclass(frozen=True)
class Mutation:
    key: str
    domain: str
    function: str
    operator: str
    shapes: tuple[str, ...]
    edits: tuple[Edit, ...]
    trap: tuple[Edit, ...] = ()
    pin_split: str | None = None   # force a split (used for the live-demo task)
    note: str = ""

    @property
    def file(self) -> str:
        return self.edits[0].file


def _m(key, domain, function, operator, shapes, file, search, replace, *, trap=(), pin=None, note="", extra=()):
    edits = (Edit(file, search, replace), *extra)
    return Mutation(key, domain, function, operator, tuple(shapes.split()), edits, tuple(trap), pin, note)


L = "src/ledgerly/"

MUTATIONS: list[Mutation] = [
    # ---------------- ledgerly ----------------
    _m("alloc-guard", "ledgerly", "allocate", "wrong-comparison", "deep-call-chain regression-trap",
       L + "money.py",
       "    if total_weight <= 0:\n",
       "    if total_weight >= 0:\n",
       trap=[Edit(L + "money.py",
                  "    if total_weight >= 0:\n        raise ValueError(\"weights must sum to a positive number\")\n",
                  "")],
       pin="heldout",
       note="LIVE DEMO: invoice tests fail, traceback ends in money.allocate; deleting the guard breaks the rejection test"),
    _m("alloc-order", "ledgerly", "allocate", "inverted-condition", "deep-call-chain",
       L + "money.py",
       "key=lambda i: raw[i] - shares[i], reverse=True)",
       "key=lambda i: raw[i] - shares[i], reverse=False)"),
    _m("rounding-mode", "ledgerly", "quantize", "wrong-rounding-mode", "one-root-many",
       L + "money.py",
       "    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)\n",
       "    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_EVEN)\n",
       extra=[Edit(L + "money.py", "from decimal import ROUND_HALF_UP, Decimal\n",
                   "from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal\n")]),
    _m("total-return", "ledgerly", "total", "missing-return", "misleading-surface",
       L + "money.py",
       "        result = result + item\n    return result\n",
       "        result = result + item\n"),
    _m("overdue-boundary", "ledgerly", "Ledger.status", "off-by-one", "regression-trap",
       L + "payments.py",
       "        if today > self.invoices[number].due_date():\n",
       "        if today >= self.invoices[number].due_date():\n",
       trap=[Edit(L + "invoice.py",
                  "        return self.issued + timedelta(days=self.terms_days)\n",
                  "        return self.issued + timedelta(days=self.terms_days + 1)\n")]),
    _m("coupon-cap", "ledgerly", "coupon_discount", "wrong-comparison", "one-root-many",
       L + "discounts.py",
       "    return min(Money(value, subtotal.currency), subtotal)\n",
       "    return max(Money(value, subtotal.currency), subtotal)\n"),
    _m("lookup-return", "ledgerly", "lookup", "missing-return", "misleading-surface",
       L + "tax.py",
       "        return RATES[code]\n",
       "        RATES[code]\n"),
]

S = "src/stockroom/"

MUTATIONS += [
    # ---------------- stockroom ----------------
    _m("onhand-filter", "stockroom", "Inventory.on_hand", "inverted-condition", "deep-call-chain",
       S + "inventory.py",
       "            return sum(q for (s, _), q in self._on_hand.items() if s == sku)\n",
       "            return sum(q for (s, _), q in self._on_hand.items() if s != sku)\n"),
    _m("reorder-boundary", "stockroom", "needs_reorder", "wrong-comparison", "regression-trap",
       S + "reorder.py",
       "    return pos <= product.reorder_point\n",
       "    return pos < product.reorder_point\n",
       trap=[Edit(S + "reorder.py", "    if not needs_reorder(product, pos):\n        return 0\n", "")]),
    _m("fifo-layer", "stockroom", "FifoLedger.consume", "off-by-one-index", "one-root-many",
       S + "valuation.py",
       "            layer = layers[0]\n",
       "            layer = layers[-1]\n"),
    _m("catalog-return", "stockroom", "Catalog.get", "missing-return", "misleading-surface",
       S + "catalog.py",
       "            return self._products[sku]\n",
       "            self._products[sku]\n"),
    _m("transfer-swap", "stockroom", "Inventory.transfer", "swapped-args", "misleading-surface",
       S + "inventory.py",
       "        self.ship(sku, qty, source)\n        self.receive(sku, qty, dest)\n",
       "        self.ship(sku, qty, dest)\n        self.receive(sku, qty, source)\n"),
    _m("pack-rounding", "stockroom", "round_to_pack", "off-by-one", "one-root-many",
       S + "reorder.py",
       "    return (qty + pack - 1) // pack * pack\n",
       "    return (qty + pack) // pack * pack\n"),
]
