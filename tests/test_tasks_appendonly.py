"""Task suite is append-only: v1 ids, mutations and splits are frozen (results on them stay valid)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V1 = {
    "csvflow-01": "group-return",
    "csvflow-02": "line-numbers",
    "ledgerly-01": "alloc-guard",
    "ledgerly-02": "lookup-return",
    "ledgerly-03": "rounding-mode",
    "ledgerly-04": "coupon-cap",
    "ledgerly-05": "alloc-order",
    "ledgerly-06": "total-return",
    "ledgerly-07": "overdue-boundary",
    "ledgerly-08": "discount-guard",
    "ratekeeper-01": "plan-return",
    "ratekeeper-02": "cost-default",
    "ratekeeper-03": "wait-swap",
    "ratekeeper-04": "sliding-evict",
    "ratekeeper-05": "quota-remaining",
    "ratekeeper-06": "take-guard",
    "slotbook-01": "overlap-adjacent",
    "slotbook-02": "series-range",
    "slotbook-03": "directory-return",
    "slotbook-04": "closes-default",
    "slotbook-05": "gaps-boundary",
    "slotbook-06": "zone-sign",
    "stockroom-01": "transfer-swap",
    "stockroom-02": "pack-rounding",
    "stockroom-03": "fifo-layer",
    "stockroom-04": "onhand-filter",
    "stockroom-05": "reorder-boundary",
    "stockroom-06": "catalog-return"
}
V1_FULL = {"train": ["ratekeeper-03", "stockroom-04", "ledgerly-03", "slotbook-06", "stockroom-03", "ratekeeper-05", "slotbook-02", "ratekeeper-04", "stockroom-01", "ratekeeper-01", "slotbook-05", "stockroom-06"], "gate": ["ledgerly-05", "slotbook-01", "stockroom-02", "ledgerly-07", "slotbook-03", "ledgerly-06"], "heldout": ["csvflow-01", "csvflow-02", "ledgerly-01", "slotbook-04", "ratekeeper-02", "ledgerly-04", "stockroom-05", "ledgerly-02"]}


def test_v1_ids_and_splits_are_frozen():
    index = json.loads((ROOT / "tasks" / "index.json").read_text())
    splits = json.loads((ROOT / "tasks" / "splits.json").read_text())
    assert {t: index[t]["mutationKey"] for t in V1} == V1
    assert splits["profiles"]["full"] == V1_FULL
    assert all(index[t]["suite"] == "v1" for t in V1)


def test_v2_profile_extends_full_and_never_mixes_splits():
    splits = json.loads((ROOT / "tasks" / "splits.json").read_text())["profiles"]
    v2, full, new = splits["v2"], splits["full"], splits["v2new"]
    for s in ("train", "gate", "heldout"):
        assert v2[s] == full[s] + new[s]
    seen = [t for s in ("train", "gate", "heldout") for t in v2[s]]
    assert len(seen) == len(set(seen))
    assert not any(t.startswith(("csvflow", "gradebook")) for t in v2["train"] + v2["gate"])   # held-out-only domains


# Suite v2 as first used for experiments (2026-10-05, incl. the gradebook domain). Append-only from here on.
V2 = {
    "csvflow-03": "missing-cols",
    "csvflow-04": "blank-any",
    "csvflow-05": "required-invert",
    "csvflow-06": "median-even",
    "csvflow-07": "header-lower",
    "csvflow-08": "bool-false",
    "gradebook-01": "points-return",
    "gradebook-02": "band-boundary",
    "gradebook-03": "late-sign",
    "gradebook-04": "percent-guard",
    "gradebook-05": "curve-cap",
    "gradebook-06": "reweight-missing",
    "gradebook-07": "shift-cap",
    "gradebook-08": "late-cutoff",
    "gradebook-09": "negative-weight-guard",
    "gradebook-10": "ignore-drop",
    "gradebook-11": "gpa-by-count",
    "gradebook-12": "percent-rounding",
    "ledgerly-09": "overpay-guard",
    "ledgerly-10": "days-late-swap",
    "ledgerly-11": "inclusive-split",
    "ledgerly-12": "rate-inverse",
    "ledgerly-13": "exclusive-filter",
    "ledgerly-14": "aging-boundary",
    "ratekeeper-07": "rate-fraction",
    "ratekeeper-08": "quota-guard",
    "ratekeeper-09": "take-boundary",
    "ratekeeper-10": "quota-check",
    "ratekeeper-11": "elapsed-swap",
    "ratekeeper-12": "advance-guard",
    "ratekeeper-13": "fixed-allow",
    "ratekeeper-14": "limit-header",
    "ratekeeper-15": "refill-cap",
    "slotbook-07": "fits-capacity",
    "slotbook-08": "intersection-swap",
    "slotbook-09": "merge-touching",
    "slotbook-10": "minutes-unit",
    "slotbook-11": "free-min",
    "slotbook-12": "capacity-guard",
    "slotbook-13": "room-order",
    "slotbook-14": "contains-end",
    "slotbook-15": "to-zone-replace",
    "stockroom-07": "pack-guard",
    "stockroom-08": "average-swap",
    "stockroom-09": "locations-zero",
    "stockroom-10": "expire-boundary",
    "stockroom-11": "report-sort",
    "stockroom-12": "pick-take",
    "stockroom-13": "consume-guard",
    "stockroom-14": "available-sign",
    "stockroom-15": "shortfall-term",
    "stockroom-16": "ship-guard"
}
V2NEW = {"train": ["ledgerly-09", "ledgerly-10", "ledgerly-11", "ledgerly-13", "ratekeeper-08", "ratekeeper-13", "slotbook-07", "slotbook-08", "slotbook-09", "slotbook-10", "stockroom-07", "stockroom-09", "stockroom-11", "stockroom-14"], "gate": ["ledgerly-14", "ratekeeper-07", "ratekeeper-11", "ratekeeper-12", "slotbook-15", "stockroom-08", "stockroom-10", "stockroom-12"], "heldout": ["csvflow-03", "csvflow-04", "csvflow-05", "csvflow-06", "csvflow-07", "csvflow-08", "gradebook-01", "gradebook-02", "gradebook-03", "gradebook-04", "gradebook-05", "gradebook-06", "gradebook-07", "gradebook-08", "gradebook-09", "gradebook-10", "gradebook-11", "gradebook-12", "ledgerly-12", "ratekeeper-09", "ratekeeper-10", "ratekeeper-14", "ratekeeper-15", "slotbook-11", "slotbook-12", "slotbook-13", "slotbook-14", "stockroom-13", "stockroom-15", "stockroom-16"]}


def test_v2_ids_and_splits_are_frozen():
    index = json.loads((ROOT / "tasks" / "index.json").read_text())
    splits = json.loads((ROOT / "tasks" / "splits.json").read_text())["profiles"]
    assert {t: index[t]["mutationKey"] for t in V2} == V2
    for s in ("train", "gate", "heldout"):
        assert splits["v2new"][s][: len(V2NEW[s])] == V2NEW[s]
