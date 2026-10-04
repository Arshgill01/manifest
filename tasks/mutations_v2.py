"""Suite v2: more injected bugs on the same five templates (append-only; v1 ids and splits never change).

Same rules as `mutations.py`: one root cause per task, claimed shapes are verified mechanically by
`tasks.gen`. Candidates whose claimed shapes do not hold are dropped by the generator run that
produced this list (see `python -m tasks.gen --explore-v2`), so every entry here verifies.
"""

from __future__ import annotations

import dataclasses

from tasks.mutations import Edit, _m

L, S, B, R, C = "src/ledgerly/", "src/stockroom/", "src/slotbook/", "src/ratekeeper/", "src/csvflow/"


def guard_trap(file: str, mutated_guard: str, raise_line: str) -> list[Edit]:
    """The classic tempting fix for an over-eager guard: delete the guard and its raise."""
    return [Edit(file, mutated_guard + raise_line, "")]


# (key, domain, function, operator, file, search, replace, trap)
CANDIDATES = [
    # ---------------- ledgerly
    ("vol-tier-boundary", "ledgerly", "volume_percent", "off-by-one", L + "discounts.py",
     "        if quantity >= tier.min_qty:\n", "        if quantity > tier.min_qty:\n", ()),
    ("inclusive-split", "ledgerly", "split_inclusive", "wrong-operator", L + "tax.py",
     "    net = Money(gross.amount / (1 + rate.rate), gross.currency)\n",
     "    net = Money(gross.amount * (1 - rate.rate), gross.currency)\n", ()),
    ("float-repr", "ledgerly", "to_decimal", "wrong-conversion", L + "money.py",
     "        return Decimal(repr(value))\n", "        return Decimal(value)\n", ()),
    ("sub-swap", "ledgerly", "Money.__sub__", "swapped-args", L + "money.py",
     "        return Money(self.amount - other.amount, self.currency)\n",
     "        return Money(other.amount - self.amount, self.currency)\n", ()),
    ("inclusive-invert", "ledgerly", "tax_on", "inverted-condition", L + "tax.py",
     "    if rate.inclusive:\n        return split_inclusive(net, rate)[1]\n",
     "    if not rate.inclusive:\n        return split_inclusive(net, rate)[1]\n", ()),
    ("overpay-guard", "ledgerly", "Ledger.pay", "wrong-comparison", L + "payments.py",
     "        if self.balance(number) < payment.amount:\n", "        if self.balance(number) <= payment.amount:\n",
     guard_trap(L + "payments.py", "        if self.balance(number) <= payment.amount:\n",
                "            raise OverpaymentError(f\"{number}: payment {payment.amount} exceeds balance\")\n")),
    ("aging-boundary", "ledgerly", "Ledger.aging", "off-by-one", L + "payments.py",
     "                if limit is None or late <= limit:\n", "                if limit is None or late < limit:\n", ()),
    ("rate-inverse", "ledgerly", "rate", "missing-inverse", L + "currency.py",
     "        return 1 / RATES[(target, source)]\n", "        return RATES[(target, source)]\n", ()),
    ("effective-min", "ledgerly", "LineItem.effective_discount_percent", "wrong-comparison", L + "line_items.py",
     "        return max(Decimal(self.discount_percent), volume_percent(self.quantity))\n",
     "        return min(Decimal(self.discount_percent), volume_percent(self.quantity))\n", ()),
    ("exclusive-filter", "ledgerly", "Invoice.exclusive_tax_total", "inverted-condition", L + "invoice.py",
     "            (t for code, t in self.tax_breakdown().items() if not lookup(code).inclusive),\n",
     "            (t for code, t in self.tax_breakdown().items() if lookup(code).inclusive),\n", ()),
    ("days-late-swap", "ledgerly", "Ledger.days_late", "swapped-args", L + "payments.py",
     "        return max(0, (today - self.invoices[number].due_date()).days)\n",
     "        return max(0, (self.invoices[number].due_date() - today).days)\n", ()),
    # ---------------- stockroom
    ("ship-guard", "stockroom", "Inventory.ship", "wrong-comparison", S + "inventory.py",
     "        if qty > have:\n", "        if qty >= have:\n",
     guard_trap(S + "inventory.py", "        if qty >= have:\n",
                "            raise InsufficientStock(f\"{sku}@{location}: need {qty}, have {have}\")\n")),
    ("locations-zero", "stockroom", "Inventory.locations", "wrong-comparison", S + "inventory.py",
     "if s == sku and q > 0)\n", "if s == sku and q >= 0)\n", ()),
    ("pick-take", "stockroom", "Inventory.pick", "wrong-comparison", S + "inventory.py",
     "            take = min(self.on_hand(sku, loc), remaining)\n", "            take = max(self.on_hand(sku, loc), remaining)\n", ()),
    ("expire-boundary", "stockroom", "ReservationBook.expire", "wrong-comparison", S + "reservations.py",
     "if r.expires_at <= now]\n", "if r.expires_at < now]\n", ()),
    ("available-sign", "stockroom", "ReservationBook.available", "inverted-sign", S + "reservations.py",
     "        return self.inventory.on_hand(sku) - self.reserved(sku)\n",
     "        return self.inventory.on_hand(sku) + self.reserved(sku)\n", ()),
    ("position-incoming", "stockroom", "position", "inverted-sign", S + "reorder.py",
     "    return book.available(product.sku) + incoming\n", "    return book.available(product.sku) - incoming\n", ()),
    ("shortfall-term", "stockroom", "suggested_order", "missing-term", S + "reorder.py",
     "    shortfall = product.reorder_point + product.reorder_qty - pos\n",
     "    shortfall = product.reorder_qty - pos\n", ()),
    ("arrival-unit", "stockroom", "expected_arrival", "wrong-unit", S + "reorder.py",
     "    return ordered_on + timedelta(days=product.lead_time_days)\n",
     "    return ordered_on + timedelta(weeks=product.lead_time_days)\n", ()),
    ("consume-guard", "stockroom", "FifoLedger.consume", "wrong-comparison", S + "valuation.py",
     "        if qty > self.quantity(sku):\n", "        if qty >= self.quantity(sku):\n",
     guard_trap(S + "valuation.py", "        if qty >= self.quantity(sku):\n",
                "            raise InsufficientStock(f\"{sku}: cannot consume {qty}\")\n")),
    ("report-sort", "stockroom", "reorder_report", "swapped-args", S + "report.py",
     "    return sorted(lines, key=lambda line: (line.arrives, line.sku))\n",
     "    return sorted(lines, key=lambda line: (line.sku, line.arrives))\n", ()),
    ("pack-guard", "stockroom", "Catalog.add", "off-by-one", S + "catalog.py",
     "        if product.pack_size < 1:\n", "        if product.pack_size <= 1:\n",
     guard_trap(S + "catalog.py", "        if product.pack_size <= 1:\n",
                "            raise ValueError(f\"{product.sku}: pack size must be at least 1\")\n")),
    ("average-swap", "stockroom", "FifoLedger.average_cost", "swapped-args", S + "valuation.py",
     "        return (self.value(sku) / qty).quantize(CENT) if qty else Decimal(\"0.00\")\n",
     "        return (qty / self.value(sku)).quantize(CENT) if qty else Decimal(\"0.00\")\n", ()),
    # ---------------- slotbook
    ("contains-end", "slotbook", "TimeRange.contains", "off-by-one", B + "timerange.py",
     "        return self.start <= moment < self.end\n", "        return self.start <= moment <= self.end\n", ()),
    ("intersection-swap", "slotbook", "TimeRange.intersection", "swapped-args", B + "timerange.py",
     "        start, end = max(self.start, other.start), min(self.end, other.end)\n",
     "        start, end = min(self.start, other.start), max(self.end, other.end)\n", ()),
    ("merge-touching", "slotbook", "merge", "wrong-comparison", B + "timerange.py",
     "        if merged and r.start <= merged[-1].end:\n", "        if merged and r.start < merged[-1].end:\n", ()),
    ("minutes-unit", "slotbook", "TimeRange.minutes", "wrong-constant", B + "timerange.py",
     "        return int(self.duration.total_seconds() // 60)\n", "        return int(self.duration.total_seconds() % 60)\n", ()),
    ("capacity-guard", "slotbook", "Calendar.check", "wrong-comparison", B + "bookings.py",
     "        if attendees > room.capacity:\n", "        if attendees >= room.capacity:\n",
     guard_trap(B + "bookings.py", "        if attendees >= room.capacity:\n",
                "            raise OverCapacity(f\"{room_name} holds {room.capacity}, asked for {attendees}\")\n")),
    ("hours-end", "slotbook", "Calendar.check", "off-by-one", B + "bookings.py",
     "        if not (hours.start <= when.start and when.end <= hours.end):\n",
     "        if not (hours.start <= when.start and when.end < hours.end):\n", ()),
    ("slot-tie", "slotbook", "find_slot", "wrong-comparison", B + "availability.py",
     "            if best is None or candidate.start < best[1].start:\n",
     "            if best is None or candidate.start <= best[1].start:\n", ()),
    ("free-min", "slotbook", "free_slots", "off-by-one", B + "availability.py",
     "    return [g for g in gaps(hours, busy) if g.minutes() >= minutes]\n",
     "    return [g for g in gaps(hours, busy) if g.minutes() > minutes]\n", ()),
    ("fits-capacity", "slotbook", "Directory.rooms_with_capacity", "off-by-one", B + "resources.py",
     "        fits = [r for r in self._rooms.values() if r.capacity >= people]\n",
     "        fits = [r for r in self._rooms.values() if r.capacity > people]\n", ()),
    ("room-order", "slotbook", "Directory.rooms_with_capacity", "swapped-args", B + "resources.py",
     "        return sorted(fits, key=lambda r: (r.capacity, r.name))\n",
     "        return sorted(fits, key=lambda r: (r.name, r.capacity))\n", ()),
    ("to-zone-replace", "slotbook", "to_zone", "wrong-call", B + "zones.py",
     "    return moment.astimezone(zone(name))\n", "    return moment.replace(tzinfo=zone(name))\n", ()),
    ("series-guard", "slotbook", "occurrences", "off-by-one", B + "recurrence.py",
     "    if count < 1:\n", "    if count <= 1:\n",
     guard_trap(B + "recurrence.py", "    if count <= 1:\n", "        raise ValueError(\"a series needs at least one occurrence\")\n")),
    # ---------------- ratekeeper
    ("refill-cap", "ratekeeper", "TokenBucket._refill", "wrong-comparison", R + "bucket.py",
     "        self.tokens = min(Fraction(self.capacity), self.tokens + elapsed * self.rate)\n",
     "        self.tokens = max(Fraction(self.capacity), self.tokens + elapsed * self.rate)\n", ()),
    ("elapsed-swap", "ratekeeper", "TokenBucket._refill", "swapped-args", R + "bucket.py",
     "        elapsed = max(0, now - self.updated)\n", "        elapsed = max(0, self.updated - now)\n", ()),
    ("take-boundary", "ratekeeper", "TokenBucket.try_take", "off-by-one", R + "bucket.py",
     "        if self.tokens >= n:\n", "        if self.tokens > n:\n", ()),
    ("advance-guard", "ratekeeper", "FakeClock.advance", "wrong-comparison", R + "clock.py",
     "        if seconds < 0:\n", "        if seconds <= 0:\n",
     guard_trap(R + "clock.py", "        if seconds <= 0:\n", "            raise ValueError(\"time only moves forward\")\n")),
    ("retry-floor", "ratekeeper", "rate_limit_headers", "wrong-rounding-mode", R + "headers.py",
     "        headers[\"Retry-After\"] = str(max(1, math.ceil(decision.retry_after)))\n",
     "        headers[\"Retry-After\"] = str(max(1, math.floor(decision.retry_after)))\n", ()),
    ("limit-header", "ratekeeper", "rate_limit_headers", "wrong-field", R + "headers.py",
     "        \"X-RateLimit-Limit\": str(plan.per_minute),\n", "        \"X-RateLimit-Limit\": str(plan.burst),\n", ()),
    ("quota-check", "ratekeeper", "RateLimiter.check", "off-by-one", R + "limiter.py",
     "        if quota.remaining() < cost:\n", "        if quota.remaining() <= cost:\n", ()),
    ("rate-fraction", "ratekeeper", "RateLimiter._state", "swapped-args", R + "limiter.py",
     "            self._buckets[key] = TokenBucket(plan.burst, Fraction(plan.per_minute, 60), self.clock)\n",
     "            self._buckets[key] = TokenBucket(plan.burst, Fraction(60, plan.per_minute), self.clock)\n", ()),
    ("reset-sign", "ratekeeper", "DailyQuota.seconds_until_reset", "inverted-sign", R + "quota.py",
     "        return (self._day() + 1) * DAY - self.clock.now()\n", "        return (self._day() + 1) * DAY + self.clock.now()\n", ()),
    ("quota-guard", "ratekeeper", "DailyQuota.consume", "wrong-comparison", R + "quota.py",
     "        if n > self.remaining():\n", "        if n >= self.remaining():\n",
     guard_trap(R + "quota.py", "        if n >= self.remaining():\n",
                "            raise QuotaExceeded(f\"daily quota of {self.limit} exhausted\")\n")),
    ("reset-at-index", "ratekeeper", "SlidingWindowLog.reset_at", "off-by-one-index", R + "window.py",
     "        return self.log[0] + self.window if self.log else self.clock.now()\n",
     "        return self.log[-1] + self.window if self.log else self.clock.now()\n", ()),
    ("fixed-allow", "ratekeeper", "FixedWindowCounter.allow", "off-by-one", R + "window.py",
     "        if count < self.limit:\n            self.counts[start] = count + 1\n",
     "        if count <= self.limit:\n            self.counts[start] = count + 1\n", ()),
    # ---------------- csvflow (held-out only)
    ("median-even", "csvflow", "median", "off-by-one-index", C + "aggregate.py",
     "    return (ordered[mid - 1] + ordered[mid]) / 2\n", "    return (ordered[mid] + ordered[mid + 1]) / 2\n", ()),
    ("header-lower", "csvflow", "normalize_header", "missing-call", C + "reader.py",
     "    return \"_\".join(name.strip().lower().split())\n", "    return \"_\".join(name.strip().split())\n", ()),
    ("blank-any", "csvflow", "read_rows", "wrong-quantifier", C + "reader.py",
     "        if not fields or all(not f.strip() for f in fields):\n",
     "        if not fields or any(not f.strip() for f in fields):\n", ()),
    ("required-invert", "csvflow", "coerce", "inverted-condition", C + "schema.py",
     "        if column.required:\n            raise BadValue", "        if not column.required:\n            raise BadValue", ()),
    ("bool-false", "csvflow", "coerce", "missing-value", C + "schema.py",
     "FALSE = {\"false\", \"no\", \"n\", \"0\"}\n", "FALSE = {\"false\", \"no\", \"n\"}\n", ()),
    ("dedupe-seen", "csvflow", "dedupe", "inverted-condition", C + "transforms.py",
     "        if key in seen:\n            continue\n", "        if key not in seen:\n            continue\n", ()),
    ("missing-cols", "csvflow", "validate", "inverted-condition", C + "validate.py",
     "        missing = [c.name for c in schema.columns if c.required and c.name not in rows[0]]\n",
     "        missing = [c.name for c in schema.columns if c.required and c.name in rows[0]]\n", ()),
    ("filter-invert", "csvflow", "filter_rows", "inverted-condition", C + "transforms.py",
     "    return [row for row in rows if predicate(row)]\n", "    return [row for row in rows if not predicate(row)]\n", ()),
    ("mean-denominator", "csvflow", "summarize", "off-by-one", C + "aggregate.py",
     "            \"mean\": round(total / len(values), 2),\n", "            \"mean\": round(total / (len(values) - 1), 2),\n", ()),
]

ALL_SHAPES = "deep-call-chain one-root-many misleading-surface local"

# key -> verified shapes, primary first (regression-trap > deep-call-chain > misleading-surface > one-root-many > local).
# Produced by exploring every CANDIDATE with all shapes claimed; candidates with no verified shape are left out.
VERIFIED: dict[str, str] = {
    'inclusive-split': 'one-root-many',
    'overpay-guard': 'regression-trap local',
    'aging-boundary': 'local',
    'rate-inverse': 'local',
    'exclusive-filter': 'one-root-many',
    'days-late-swap': 'local',
    'ship-guard': 'regression-trap',
    'locations-zero': 'local',
    'pick-take': 'misleading-surface',
    'expire-boundary': 'local',
    'available-sign': 'one-root-many',
    'shortfall-term': 'one-root-many',
    'consume-guard': 'regression-trap local',
    'report-sort': 'local',
    'pack-guard': 'regression-trap',
    'average-swap': 'local',
    'contains-end': 'local',
    'intersection-swap': 'local',
    'merge-touching': 'local',
    'minutes-unit': 'one-root-many',
    'capacity-guard': 'local',
    'free-min': 'local',
    'fits-capacity': 'local',
    'room-order': 'local',
    'to-zone-replace': 'local',
    'refill-cap': 'one-root-many',
    'elapsed-swap': 'one-root-many',
    'take-boundary': 'one-root-many',
    'advance-guard': 'regression-trap deep-call-chain',
    'limit-header': 'local',
    'quota-check': 'local',
    'rate-fraction': 'one-root-many',
    'quota-guard': 'regression-trap',
    'fixed-allow': 'local',
    'median-even': 'one-root-many',
    'header-lower': 'one-root-many',
    'blank-any': 'one-root-many',
    'required-invert': 'one-root-many',
    'bool-false': 'local',
    'missing-cols': 'one-root-many',
}


def candidate_mutations(shapes_for: dict[str, str] | None = None):
    """Mutations for every candidate; claims = verified shapes if known, else all (exploration)."""
    out = []
    for key, domain, fn, op, file, search, replace, trap in CANDIDATES:
        claim = (shapes_for or {}).get(key)
        if claim is None:
            claim = ALL_SHAPES + (" regression-trap" if trap else "")
        m = _m(key, domain, fn, op, claim, file, search, replace, trap=list(trap))
        out.append(dataclasses.replace(m, strict=True))
    return out


def mutations_v2():
    return [m for m in candidate_mutations(VERIFIED) if m.key in VERIFIED]
