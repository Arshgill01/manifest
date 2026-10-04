"""Is the student deterministic? Compare the same tasks across two event logs, call by call.

    uv run python -m growth.determinism <log A> <log B>

For every task both logs ran (same split), reports whether pass/fail agree and the first student call whose
response differs (temperature 0 should make them identical; KV-prefix reuse and batch shapes on CPU can
still perturb logits). The gate in growth assumes repeated runs of an unchanged harness agree.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from harness.log import read_events


def per_task(events: list[dict]) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    cur: dict[tuple, dict] = {}
    for e in events:
        if not e.get("taskId") or e.get("cached"):
            continue
        k = (e.get("split"), e["taskId"])
        if e["type"] == "task.start":
            cur[k] = {"responses": [], "tools": []}
        elif k in cur:
            if e["type"] == "model.call" and e.get("role") == "student":
                cur[k]["responses"].append(e.get("response") or "")
            elif e["type"] == "tool.call":
                cur[k]["tools"].append((e.get("tool"), str(e.get("args"))))
            elif e["type"] == "task.end":
                out[k] = {**cur.pop(k), "pass": e.get("pass")}
    return out


def compare(a: dict, b: dict) -> list[dict]:
    rows = []
    for k in sorted(set(a) & set(b)):
        ra, rb = a[k]["responses"], b[k]["responses"]
        first = next((i for i, (x, y) in enumerate(zip(ra, rb)) if x != y), None)
        if first is None and len(ra) != len(rb):
            first = min(len(ra), len(rb))
        rows.append({"task": k[1], "split": k[0], "passA": a[k]["pass"], "passB": b[k]["pass"],
                     "calls": (len(ra), len(rb)), "identical": first is None, "firstDiff": first})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    x = ap.parse_args(argv)
    rows = compare(per_task(read_events(x.a)), per_task(read_events(x.b)))
    for r in rows:
        print(f"{r['task']:14} pass {r['passA']!s:5} vs {r['passB']!s:5}  calls {r['calls']}  "
              + ("identical" if r["identical"] else f"first differing student call: #{r['firstDiff'] + 1}"))
    same = sum(r["identical"] for r in rows)
    agree = sum(r["passA"] == r["passB"] for r in rows)
    print(f"\n{same}/{len(rows)} tasks identical call-for-call; {agree}/{len(rows)} agree on pass/fail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
