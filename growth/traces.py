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
MAX_STR_LONG = 700  # failure text is what the teacher needs most
LONG_KEYS = {"summary", "error", "output", "result", "hypothesis"}
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
    extras = {k: _clip(v, MAX_STR_LONG if k in LONG_KEYS else MAX_STR) for k, v in e.items() if k not in BASE_KEYS and k != "type"}
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


_VOLATILE = {"repeat", "promptTokens", "outTokens", "ms"}


def _sig(s: dict) -> str:
    return json.dumps({k: v for k, v in s.items() if k not in _VOLATILE}, sort_keys=True, default=str)


def _collapse(steps: list[dict]) -> list[dict]:
    """Collapse identical consecutive steps (`repeat`), then repeated cycles of 2-4 steps (`{"loop": n, "times": k}`)."""
    out: list[dict] = []
    for s in steps:
        if out and _sig(out[-1]) == _sig(s):
            out[-1]["repeat"] = out[-1].get("repeat", 1) + 1
        else:
            out.append(dict(s))
    sigs = [_sig(s) for s in out]
    res: list[dict] = []
    i = 0
    while i < len(out):
        for p in (2, 3, 4):
            k = 1
            while sigs[i + k * p: i + (k + 1) * p] == sigs[i: i + p] and i + (k + 1) * p <= len(out):
                k += 1
            if k >= 2:
                res.extend(out[i: i + p])
                res.append({"loop": f"previous {p} steps repeated", "times": k})
                i += k * p
                break
        else:
            res.append(out[i])
            i += 1
    return res


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
            e for e in (fallback_events or []) if e.get("taskId") == tid and e.get("split") in (None, "train")
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
