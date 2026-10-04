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
    assert all(t.startswith("csvflow") is False for t in v2["train"] + v2["gate"])   # novel domain held-out only
