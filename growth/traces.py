"""Failed-trace compression for the teacher prompt (SPEC §5.1–5.2).

Function-level: which routine ran, the tool calls with their inputs/outputs, and the student calls.
Built ONLY from train-split events: anything tagged with another split or another task is dropped,
and tasks outside `train_ids` are never considered.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

BASE_KEYS = {"ts", "type", "round", "taskId", "split"}
MAX_STR = 300
HEAD, TAIL = 14, 14


def _clip(v: Any, n: int = MAX_STR) -> Any:
    if isinstance(v, str):
        return v if len(v) <= n else v[: n - 20] + f"…[+{len(v) - n + 20} chars]"
    if isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False, default=str)
        return v if len(s) <= n else _clip(s, n)
    return v


def _step(e: dict) -> dict | None:
    t = e.get("type")
    extras = {k: _clip(v) for k, v in e.items() if k not in BASE_KEYS and k != "type"}
    if t == "routine.call":
        extras.pop("ms", None)
        return {"routine": extras.pop("routine", "?"), **extras}
    if t == "model.call":
        if e.get("role") == "teacher":
            return None
        for k in ("model", "role", "ms", "cacheHitTokens", "costUsd"):
            extras.pop(k, None)
        return {"student": extras.pop("purpose", "?"), **extras}
    if t == "tool.call":
        return {"tool": extras.pop("tool", "?"), **extras}
    if t == "warden.block":
        return {"wardenBlock": extras.pop("attempted", "?"), **extras}
    return None


def _collapse(steps: list[dict]) -> list[dict]:
    out: list[dict] = []
    for s in steps:
        if out and {k: v for k, v in out[-1].items() if k != "repeat"} == s:
            out[-1]["repeat"] = out[-1].get("repeat", 1) + 1
        else:
            out.append(dict(s))
    return out


def compress_task(task_id: str, events: list[dict]) -> dict:
    header: dict[str, Any] = {"taskId": task_id}
    steps: list[dict] = []
    outcome: dict[str, Any] = {}
    for e in events:
        if e.get("split") not in (None, "train") or e.get("taskId") not in (None, task_id):
            continue
        t = e.get("type")
        if t == "task.start":
            header.update({k: e[k] for k in ("domain", "bugShape") if k in e})
        elif t == "task.end":
            outcome = {k: e[k] for k in ("pass", "steps", "modelCalls", "routineCalls", "ms") if k in e}
        else:
            s = _step(e)
            if s is not None:
                steps.append(s)
    steps = _collapse(steps)
    if len(steps) > HEAD + TAIL:
        steps = steps[:HEAD] + [{"omitted": len(steps) - HEAD - TAIL}] + steps[-TAIL:]
    return {**header, "outcome": outcome, "trace": steps}


def compress_failed_traces(
    train_result: dict,
    *,
    train_ids: list[str] | set[str],
    max_traces: int = 6,
    fallback_events: list[dict] | None = None,
) -> list[dict]:
    """Up to `max_traces` failed train traces, spread across bug shapes / domains, deterministic order."""
    allowed = set(train_ids)
    failed = [
        r for r in train_result.get("results", [])
        if not r.get("pass") and r.get("taskId") in allowed
    ]
    compressed = []
    for r in sorted(failed, key=lambda r: r["taskId"]):
        tid = r["taskId"]
        events = r.get("events") or [
            e for e in (fallback_events or []) if e.get("taskId") == tid and e.get("split") == "train"
        ]
        c = compress_task(tid, events)
        if not c["outcome"]:
            c["outcome"] = {k: r[k] for k in ("pass", "steps", "modelCalls", "routineCalls", "ms") if k in r}
        compressed.append(c)

    # round-robin over bug shapes so six traces aren't all the same failure
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in compressed:
        groups[str(c.get("bugShape") or c.get("domain") or "?")].append(c)
    picked: list[dict] = []
    keys = sorted(groups)
    while len(picked) < max_traces and any(groups[k] for k in keys):
        for k in keys:
            if groups[k] and len(picked) < max_traces:
                picked.append(groups[k].pop(0))
    return picked
