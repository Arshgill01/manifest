"""Label why each failed task failed: process, knowledge, or format.

    uv run python -m tasks.labels .manifest/runs/<run>.jsonl [--json]

- format     the model could not drive the tools: unknown tools, malformed/failed edits,
             truncated outputs. If this dominates round 0, the baseline loses on syntax,
             not process, and the comparison is unfair.
- knowledge  the process was right (read the root-cause file, edited the root-cause
             function, re-ran the tests) but the fix itself was wrong.
- process    everything else: never reached the root cause, edited the wrong place,
             looped, never re-ran tests after editing, gave up early, hit the limits.

Uses only the event log plus tasks/index.json (root cause is never shown to any model).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FORMAT_ERR = re.compile(r"unknown tool|invalid|malformed|not found|no match|did not match|json|schema|missing", re.I)


def _norm(path: str) -> str:
    return str(path or "").lstrip("./")


def _touches(path: str, root_file: str) -> bool:
    p = _norm(path)
    return bool(p) and (p == root_file or root_file.endswith("/" + p) or p.endswith(root_file))


def _edit_line(task_id: str, root_file: str, search: str) -> int | None:
    src_path = ROOT / "generated" / task_id / root_file
    if not search or not src_path.exists():
        return None
    src = src_path.read_text()
    i = src.find(search)
    return None if i < 0 else src[:i].count("\n") + 1


def label_task(task_id: str, events: list[dict], meta: dict) -> dict:
    root = meta["rootCause"]
    span = root.get("span") or [root["line"], root["line"]]
    tools = [e for e in events if e["type"] == "tool.call"]
    models = [e for e in events if e["type"] == "model.call" and e.get("role") == "student"]
    end = next((e for e in events if e["type"] == "task.end"), {})
    reasons: list[str] = []

    fmt_fail = [t for t in tools if not t.get("ok") and FORMAT_ERR.search(str(t.get("summary", "")))]
    truncated = [m for m in models if m.get("doneReason") == "length"]
    blocks = [e for e in events if e["type"] == "warden.block"]

    read_root = any(t["tool"] == "read_file" and _touches(t.get("args", {}).get("path"), root["file"]) for t in tools)
    edits = [t for t in tools if t["tool"] == "edit_file"]
    good_edits = [t for t in edits if t.get("ok")]
    root_edits = [t for t in good_edits if _touches(t.get("args", {}).get("path"), root["file"])]
    in_function = [
        t for t in root_edits
        if (line := _edit_line(task_id, root["file"], t.get("args", {}).get("search", ""))) is not None
        and span[0] <= line <= span[1]
    ]
    test_edits = [t for t in edits if _norm(t.get("args", {}).get("path")).startswith("tests/")]
    last_edit_idx = max((i for i, t in enumerate(tools) if t["tool"] == "edit_file" and t.get("ok")), default=-1)
    reran_after_edit = any(t["tool"] == "run_tests" for t in tools[last_edit_idx + 1:]) if last_edit_idx >= 0 else False
    full_rerun_after_edit = any(
        t["tool"] == "run_tests" and (t.get("args") or {}).get("selector") in (None, "", "-")
        for t in tools[last_edit_idx + 1:]
    ) if last_edit_idx >= 0 else False
    sigs = Counter(json.dumps([t["tool"], t.get("args")], sort_keys=True) for t in tools)
    looped = [json.loads(s)[0] for s, n in sigs.items() if n >= 3]
    stop = end.get("stopReason") or ""

    if fmt_fail:
        reasons.append(f"{len(fmt_fail)} tool call(s) failed on format ({fmt_fail[0].get('summary', '')[:60]!r})")
    if truncated:
        reasons.append(f"{len(truncated)} truncated model output(s)")
    if not tools:
        reasons.append("never called a tool")
    if not read_root:
        reasons.append(f"never opened {root['file']}")
    if good_edits and not root_edits:
        wrong = sorted({_norm(t['args'].get('path')) for t in good_edits})
        reasons.append(f"edited the wrong file(s): {', '.join(wrong)}")
    if root_edits and not in_function:
        reasons.append(f"edited {root['file']} but not {root['function']}")
    if test_edits or blocks:
        reasons.append("tried to edit tests")
    if good_edits and not reran_after_edit:
        reasons.append("never re-ran tests after the last edit")
    if looped:
        reasons.append(f"repeated the same call 3+ times: {', '.join(looped)}")
    if not good_edits:
        reasons.append("never made a successful edit")
    if stop:
        reasons.append(f"stopped: {stop}")

    format_share = (len(fmt_fail) + len(truncated)) / max(len(tools) + len(truncated), 1)
    if (not tools and models) or format_share >= 0.5:
        label = "format"
    elif in_function and reran_after_edit and not looped:
        label = "knowledge"
    else:
        label = "process"
    return {
        "taskId": task_id, "label": label, "reasons": reasons, "bugShape": meta["bugShape"],
        "toolCalls": len(tools), "modelCalls": len(models), "readRoot": read_root,
        "editedRootFunction": bool(in_function), "reranAfterEdit": reran_after_edit,
        "fullRerunAfterEdit": full_rerun_after_edit,
    }


def label_run(path: Path) -> list[dict]:
    index = json.loads((ROOT / "index.json").read_text())
    events = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    by_task: dict[tuple, list[dict]] = {}
    for e in events:
        if e.get("taskId"):
            by_task.setdefault((e.get("round"), e["taskId"]), []).append(e)
    out = []
    for (rnd, task_id), evs in sorted(by_task.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1])):
        end = next((e for e in evs if e["type"] == "task.end"), None)
        if end is None or task_id not in index:
            continue
        if end.get("pass"):
            out.append({"taskId": task_id, "round": rnd, "label": "pass", "reasons": [], "bugShape": index[task_id]["bugShape"]})
        else:
            out.append({"round": rnd, **label_task(task_id, evs, index[task_id])})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rows = label_run(args.run)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for r in rows:
        print(f"r{r['round']} {r['taskId']:14} {r['label']:9} {r['bugShape']:18} " + "; ".join(r["reasons"]))
    counts = Counter(r["label"] for r in rows)
    print("\n" + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
