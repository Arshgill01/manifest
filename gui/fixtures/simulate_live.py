"""Re-emit the fixture run into .manifest/runs/ in real time, through EventLog, to exercise the GUI's Live mode.

    uv run python gui/fixtures/simulate_live.py               # 10x speed, whole run
    uv run python gui/fixtures/simulate_live.py --speed 4 --from-round 3 --offline

The output file is labelled `simulated` (…-simulated.jsonl). Delete it when you're done; it's not a real run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from harness.log import EventLog  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "demo-run.jsonl"
BASE = {"ts", "type", "round", "taskId", "split"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=10.0)
    ap.add_argument("--from-round", type=int, default=0)
    ap.add_argument("--offline", action="store_true", help="mark run.start online=false (no teacher)")
    ap.add_argument("--max-gap", type=float, default=3.0, help="cap any single wait (seconds, after speed-up)")
    a = ap.parse_args()

    events = [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]
    start = next(e for e in events if e["type"] == "run.start")
    body = [e for e in events if e["type"] != "run.start" and e["round"] >= a.from_round]

    log = EventLog.create("simulated", keep_in_memory=False)
    print(f"writing {log.path.relative_to(ROOT)}", flush=True)
    fields = {k: v for k, v in start.items() if k not in BASE}
    fields.update(online=not a.offline, simulated=True)
    log.set(round=a.from_round)
    log.emit("run.start", **fields)

    prev = None
    for e in body:
        t = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
        if prev is not None:
            time.sleep(min((t - prev).total_seconds() / a.speed, a.max_gap))
        prev = t
        log.set(round=e["round"], taskId=e["taskId"], split=e["split"])
        log.emit(e["type"], **{k: v for k, v in e.items() if k not in BASE})


if __name__ == "__main__":
    main()
