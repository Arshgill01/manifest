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
    strict: bool = False           # suite v2: strict misleading-surface (crash in package code, not a test assertion)

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

B = "src/slotbook/"

MUTATIONS += [
    # ---------------- slotbook ----------------
    _m("closes-default", "slotbook", "Room", "wrong-default", "deep-call-chain",
       B + "resources.py",
       "    closes: time = time(18)\n",
       "    closes: time = time(17)\n"),
    _m("gaps-boundary", "slotbook", "gaps", "wrong-comparison", "misleading-surface regression-trap",
       B + "timerange.py",
       "        if r.start > cursor:\n",
       "        if r.start >= cursor:\n",
       trap=[Edit(B + "timerange.py",
                  "        if not self.start < self.end:\n            raise InvalidRange(f\"empty or reversed range {self.start} - {self.end}\")\n",
                  "")]),
    _m("directory-return", "slotbook", "Directory.get", "missing-return", "misleading-surface",
       B + "resources.py",
       "        return self._rooms[name]\n",
       "        self._rooms[name]\n"),
    _m("series-range", "slotbook", "occurrences", "off-by-one", "one-root-many",
       B + "recurrence.py",
       "    return [first.shift(every * i) for i in range(count)]\n",
       "    return [first.shift(every * i) for i in range(1, count)]\n"),
    _m("overlap-adjacent", "slotbook", "TimeRange.overlaps", "wrong-comparison", "one-root-many",
       B + "timerange.py",
       "        return self.start < other.end and other.start < self.end\n",
       "        return self.start <= other.end and other.start <= self.end\n"),
    _m("zone-sign", "slotbook", "zone", "inverted-sign", "one-root-many",
       B + "zones.py",
       "        return timezone(timedelta(minutes=OFFSETS_MINUTES[name]), name)\n",
       "        return timezone(timedelta(minutes=-OFFSETS_MINUTES[name]), name)\n"),
]

R = "src/ratekeeper/"

MUTATIONS += [
    # ---------------- ratekeeper ----------------
    _m("wait-swap", "ratekeeper", "TokenBucket.wait_time", "swapped-args", "deep-call-chain",
       R + "bucket.py",
       "        return deficit / self.rate\n",
       "        return self.rate / deficit\n"),
    _m("sliding-evict", "ratekeeper", "SlidingWindowLog._evict", "wrong-comparison", "regression-trap",
       R + "window.py",
       "        while self.log and self.log[0] <= now - self.window:\n",
       "        while self.log and self.log[0] < now - self.window:\n",
       trap=[Edit(R + "window.py", "        if len(self.log) < self.limit:\n", "        if len(self.log) <= self.limit:\n")]),
    _m("cost-default", "ratekeeper", "RateLimiter.check", "wrong-default", "one-root-many",
       R + "limiter.py",
       "    def check(self, key: str, plan_name: str, cost: int = 1) -> Decision:\n",
       "    def check(self, key: str, plan_name: str, cost: int = 0) -> Decision:\n"),
    _m("plan-return", "ratekeeper", "get_plan", "missing-return", "misleading-surface",
       R + "quota.py",
       "    return PLANS[name]\n",
       "    PLANS[name]\n"),
    _m("quota-remaining", "ratekeeper", "DailyQuota.remaining", "off-by-one", "one-root-many",
       R + "quota.py",
       "        return max(0, self.limit - self.used_today())\n",
       "        return max(0, self.limit - self.used_today() - 1)\n"),
]

C = "src/csvflow/"

MUTATIONS += [
    # ---------------- csvflow (held-out only: a domain the teacher never sees) ----------------
    _m("line-numbers", "csvflow", "read_rows", "off-by-one", "deep-call-chain",
       C + "reader.py",
       "    for line, fields in enumerate(reader, start=2):\n",
       "    for line, fields in enumerate(reader, start=1):\n"),
    _m("group-return", "csvflow", "group_by", "missing-return", "misleading-surface",
       C + "aggregate.py",
       "        groups.setdefault(row[key], []).append(row)\n    return groups\n",
       "        groups.setdefault(row[key], []).append(row)\n"),
]

# ---------------- live-demo set ----------------
# Added after the growth run, never shown to the teacher, not part of any scored split. Same verifier.
# All are inverted guards that raise inside the root function, with "delete the guard" as the trap:
# fast to run live, and each one really is a regression trap.
DEMO_MUTATIONS: list[Mutation] = [
    _m("discount-guard", "ledgerly", "percent_off", "wrong-comparison", "regression-trap",
       L + "discounts.py",
       "    if not 0 <= pct <= 100:\n",
       "    if not 0 < pct <= 100:\n",
       trap=[Edit(L + "discounts.py",
                  "    if not 0 < pct <= 100:\n        raise ValueError(f\"discount percent out of range: {pct}\")\n", "")]),
    _m("take-guard", "ratekeeper", "TokenBucket.try_take", "wrong-comparison", "regression-trap",
       R + "bucket.py",
       "        if n > self.capacity:\n",
       "        if n >= self.capacity:\n",
       trap=[Edit(R + "bucket.py",
                  "        if n >= self.capacity:\n            raise ValueError(f\"cannot take {n} tokens from a bucket of {self.capacity}\")\n", "")]),
]
