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


# --------------------------------------------------------------------------- v2: execution graph + diagnostics
#
# Paper §3.2/§3.4: the optimizer sees each window failure as an execution graph (function invocations,
# tool and model calls, returns, errors) plus offline diagnostics E. Here: routine -> fn.call/fn.return
# (functions inside the routine) -> tool.call / model.call, rendered as indented text. The controller emits
# `routine.call` *after* a routine finishes, so inner events are buffered until it arrives.

GRAPH_MAX_LINES = 110
_FULL_SELECTORS = (None, "", "-", "*", "all")


def _tool_line(e: dict) -> str:
    args = e.get("args") or {}
    if e.get("tool") == "read_file":
        rng = f":{args.get('start')}-{args.get('end')}" if args.get("start") or args.get("end") else ""
        a = f"{args.get('path')}{rng}"
    elif e.get("tool") == "edit_file":
        a = f"{args.get('path')}, search={_clip(args.get('search', ''), 80)!r}, replace={_clip(args.get('replace', ''), 80)!r}"
    elif e.get("tool") == "run_tests":
        a = args.get("selector") or ""
    elif e.get("tool") == "bash":
        a = _clip(args.get("cmd", ""), 100)
    else:
        a = ""
    ok = "" if e.get("ok", True) else " FAILED"
    return f"tool {e.get('tool')}({a}){ok} -> {_clip(e.get('summary', ''), 160)}"


def _model_line(e: dict) -> str:
    resp = (e.get("response") or "").replace("\n", " ")
    err = f" ERROR {e['error']}" if e.get("error") else ""
    return (f"student {e.get('purpose')} ({e.get('promptTokens', 0)} prompt tok, {e.get('ms', 0) / 1000:.0f}s){err}"
            + (f" -> {_clip(resp, 220)}" if resp else ""))


def render_graph(events: list[dict], *, fn_level: bool = True, max_lines: int = GRAPH_MAX_LINES) -> list[str]:
    lines: list[str] = []
    buf: list[str] = []
    for e in events:
        t = e.get("type")
        if t == "fn.call" and fn_level:
            args = ", ".join(f"{k}={v}" for k, v in (e.get("args") or {}).items())
            buf.append("  " * (e.get("depth", 0) + 1) + f"fn {e.get('fn')}({_clip(args, 200)})")
        elif t == "fn.return" and fn_level:
            out = f"raised {e['exc']}" if e.get("exc") else f"= {_clip(str(e.get('ret')), 200)}"
            buf.append("  " * (e.get("depth", 0) + 1) + f"<- {e.get('fn')} {out}")
        elif t == "tool.call":
            depth = 2 if fn_level and any(l.lstrip().startswith("fn ") for l in buf) else 1
            buf.append("  " * depth + _tool_line(e))
        elif t == "model.call" and e.get("role") != "teacher":
            depth = 2 if fn_level and any(l.lstrip().startswith("fn ") for l in buf) else 1
            buf.append("  " * depth + _model_line(e))
        elif t == "warden.block":
            buf.append(f"  WARDEN BLOCK {e.get('attempted')}: {e.get('reason')}")
        elif t == "routine.call":
            status = "" if e.get("ok", True) else " (ERROR)"
            lines.append(f"[{e.get('routine')}]{status} {_clip(e.get('summary', ''), 200)}")
            lines.extend(buf)
            buf = []
    lines.extend(buf)  # baseline mode / a routine cut off by the budget
    # collapse identical consecutive lines, then cap
    out: list[str] = []
    for l in lines:
        if out and out[-1].split(" [x")[0] == l:
            n = int(out[-1].rsplit("[x", 1)[1][:-1]) + 1 if " [x" in out[-1] else 2
            out[-1] = f"{l} [x{n}]"
        else:
            out.append(l)
    if len(out) > max_lines:
        head = max_lines // 2
        out = out[:head] + [f"... {len(out) - max_lines} lines omitted ..."] + out[-(max_lines - head):]
    return out


def diagnostics(events: list[dict]) -> dict:
    """Offline diagnostics E (paper §3.4) from one task's events: no root-cause metadata, train only."""
    tools = [e for e in events if e.get("type") == "tool.call"]
    models = [e for e in events if e.get("type") == "model.call" and e.get("role") != "teacher"]
    end = next((e for e in reversed(events) if e.get("type") == "task.end"), {})
    reads = [t for t in tools if t.get("tool") == "read_file"]
    edits = [t for t in tools if t.get("tool") == "edit_file"]
    runs = [t for t in tools if t.get("tool") == "run_tests"]
    last_edit = max((i for i, t in enumerate(tools) if t.get("tool") == "edit_file" and t.get("ok")), default=-1)
    full_after = any(t.get("tool") == "run_tests" and (t.get("args") or {}).get("selector") in _FULL_SELECTORS
                     for t in tools[last_edit + 1:]) if last_edit >= 0 else False
    sigs: dict[str, int] = defaultdict(int)
    for t in tools:
        sigs[json.dumps([t.get("tool"), t.get("args")], sort_keys=True, default=str)] += 1
    judge = end.get("judge") or {}
    return {
        "stopReason": end.get("stopReason"),
        "steps": end.get("steps"), "studentCalls": end.get("modelCalls"),
        "finalSuite": f"{judge.get('failed', '?')} failed / {judge.get('expected', '?')} tests"
                      + (" (test files were modified: automatic fail)" if judge.get("tampered") else ""),
        "stillFailing": judge.get("failedTests", [])[:6],
        "reads": len(reads), "distinctFilesRead": len({(t.get("args") or {}).get("path") for t in reads}),
        "edits": f"{sum(1 for t in edits if t.get('ok'))} applied, {sum(1 for t in edits if not t.get('ok'))} failed",
        "testRuns": len(runs), "fullRunAfterLastEdit": full_after,
        "repeatedIdenticalToolCalls": sum(n - 1 for n in sigs.values() if n > 1),
        "studentFormatRetries": sum(1 for m in models if str(m.get("purpose", "")).endswith(":retry")),
        "studentErrors": sum(1 for m in models if m.get("error")),
        "wardenBlocks": sum(1 for e in events if e.get("type") == "warden.block"),
    }


def window_entry(task_id: str, events: list[dict], *, attempts: int, fn_level: bool = True) -> dict:
    """One failure-window entry for the teacher: train events only (anything else is dropped)."""
    own = [e for e in events if e.get("split") in (None, "train") and e.get("taskId") in (None, task_id)]
    start = next((e for e in own if e.get("type") == "task.start"), {})
    return {
        "taskId": task_id, "domain": start.get("domain"), "bugShape": start.get("bugShape"),
        "attempts": attempts, "diagnostics": diagnostics(own),
        "graph": render_graph(own, fn_level=fn_level),
        "routines": sorted({e["routine"] for e in own if e.get("type") == "routine.call"}),
    }
