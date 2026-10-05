"""RESULTS.md (v2) from committed event logs. Every number is recomputed here; nothing is hand-entered.

    uv run python -m growth.results experiments.json -o RESULTS.md

`experiments.json` lists the logs behind each experiment (SPEC §9):
  {"reference": "E1",
   "experiments": [{"id": "E1", "label": "...", "log": ".manifest/runs/....jsonl", "splits": ["heldout", ...]}],
   "growth": [{"id": "E4", "label": "...", "log": ".manifest/runs/....jsonl"}]}
Experiments may be incomplete (still running); missing tasks are reported, not hidden.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from growth.stats import bootstrap_ci, discordant, fmt_ci, mcnemar_exact, paired_ci, success_ci
from harness.log import ROOT, read_events
from tasks.labels import label_task

SPLITS = ("heldout", "gate", "train")
INFRA = ("ConnectionError", "RemoteProtocolError", "Failed to connect to Ollama", "Server disconnected")


def _index() -> dict:
    return json.loads((ROOT / "tasks" / "index.json").read_text())


def _splits() -> dict:
    return json.loads((ROOT / "tasks" / "splits.json").read_text())


def task_records(events: list[dict], splits: list[str] | None = None) -> dict[tuple[str, str, int], dict]:
    """(split, taskId, rep) -> per-run record; the last completed run of a (task, rep) in the log wins."""
    index = _index()
    out: dict[tuple[str, str], dict] = {}
    cur: dict[tuple[str, str], list[dict]] = {}
    for e in events:
        tid, split = e.get("taskId"), e.get("split")
        if not tid or (splits and split not in splits):
            continue
        key = (split, tid, e.get("rep", 0))
        if e["type"] == "task.start":
            cur[key] = [e]
            continue
        if key not in cur:
            continue
        cur[key].append(e)
        if e["type"] != "task.end":
            continue
        evs = cur.pop(key)
        if e.get("infra") or any(m in str(e.get("error") or "") for m in INFRA):
            continue  # the machine failed, not the student (Ollama killed / restarting): never scored
        student = [x for x in evs if x["type"] == "model.call" and x.get("role") == "student"]
        meta = index.get(tid, {})
        rec = {
            "taskId": tid, "split": split, "rep": e.get("rep", 0), "domain": meta.get("domain"), "bugShape": meta.get("bugShape"),
            "pass": bool(e.get("pass")), "calls": e.get("modelCalls", len(student)), "steps": e.get("steps"),
            "promptTokens": sum(x.get("promptTokens") or 0 for x in student),
            "outTokens": sum(x.get("outTokens") or 0 for x in student),
            "sec": (e.get("ms") or 0) / 1000, "stop": e.get("stopReason") or "", "cached": bool(e.get("cached")),
            "blocks": sum(1 for x in evs if x["type"] == "warden.block"),
            "routines": Counter(x["routine"] for x in evs if x["type"] == "routine.call"),
        }
        if meta and not rec["pass"]:
            lab = label_task(tid, evs, meta)
            rec["label"], rec["reasons"] = lab["label"], lab["reasons"]
        else:
            rec["label"], rec["reasons"] = ("pass" if rec["pass"] else "?"), []
        out[key] = rec
    return out


def aggregate(runs: dict[tuple[str, str, int], dict]) -> dict[tuple[str, str], dict]:
    """Average repetitions per task (the paper's R runs): pass = mean pass rate, numbers = means; the CI is then a
    task-level cluster bootstrap over these per-task means. `pass0` keeps repetition 0 for McNemar."""
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for (split, tid, rep), r in sorted(runs.items(), key=lambda kv: kv[0][2]):
        by[(split, tid)].append(r)
    out = {}
    for k, rs in by.items():
        n = len(rs)
        agg = dict(rs[0])
        agg.update(reps=n, passes=[r["pass"] for r in rs], pass0=rs[0]["pass"],
                   **{f: sum(r[f] for r in rs) / n for f in ("calls", "promptTokens", "outTokens", "sec")})
        agg["pass"] = sum(r["pass"] for r in rs) / n
        agg["label"] = "pass" if agg["pass"] == 1 else next((r["label"] for r in rs if not r["pass"]), "?")
        out[k] = agg
    return out


def _start(events: list[dict]) -> dict:
    return next((e for e in events if e["type"] == "run.start"), {})


def _row(label: str, recs: list[dict], expected: int) -> str:
    passes = [r["pass"] for r in recs]
    n = len(recs)
    sr = fmt_ci(*bootstrap_ci(passes), pct=True) if n else "–"
    calls = fmt_ci(*bootstrap_ci([r["calls"] for r in recs])) if n else "–"
    ptok = f"{sum(r['promptTokens'] for r in recs) / n / 1000:.1f}k" if n else "–"
    otok = f"{sum(r['outTokens'] for r in recs) / n:.0f}" if n else "–"
    sec = fmt_ci(*bootstrap_ci([r["sec"] for r in recs]), digits=0) if n else "–"
    stops = Counter(r["stop"] for r in recs)
    done = "" if n == expected else f" ({n}/{expected} run)"
    reps = max((r.get("reps", 1) for r in recs), default=1)
    tag = f" ×{reps}" if reps > 1 else ""
    shown = f"{sum(passes):g}" if reps == 1 else f"{sum(passes):.2f}"
    return (f"| {label}{done}{tag} | {shown}/{n} | {sr} | {calls} | {ptok} | {otok} | {sec} | "
            + ", ".join(f"{k or '?'} {v}" for k, v in stops.most_common()) + " |")


def render(cfg: dict, cfg_path: Path) -> str:
    splits_all = _splits()
    profile = cfg.get("profile", "full")
    split_ids = splits_all["profiles"][profile]
    exps = []
    for x in cfg.get("experiments", []):
        logs = [x["log"]] if isinstance(x["log"], str) else list(x["log"])   # later logs complete / repair earlier ones
        ev, recs = [], {}
        for lg in logs:
            p = ROOT / lg
            if p.exists():
                e = read_events(p)
                ev += e
                recs.update(task_records(e, x.get("splits")))
        if not ev:
            continue
        exps.append({**x, "events": ev, "start": _start(ev), "recs": aggregate(recs), "runs": recs})
    ref = next((x for x in exps if x["id"] == cfg.get("reference")), exps[0] if exps else None)

    L = ["# Results (v2)", "",
         f"Generated by `growth/results.py` from `{cfg_path.name}` and the event logs it lists (committed under "
         "`.manifest/runs/`). Nothing below is hand-entered. Protocol: SPEC §3; 95 % CIs are task-level bootstrap "
         "(10 000 resamples).", ""]
    host = next((x["start"].get("host") for x in exps if x["start"].get("host")), None)
    if host:
        L += [f"- Host: `{host.get('hostname')}`, {host.get('cpu')} × {host.get('cpus')} threads, {host.get('ramGb')} GB RAM, "
              f"CPU only; Ollama {host.get('ollamaVersion')}",
              f"- Student: `{host.get('studentModel')}` ({host.get('quantization')}, digest `{host.get('modelDigest')}`), "
              f"options `{json.dumps(host.get('studentOptions'))}`"]
    st = ref["start"] if ref else {}
    L += [f"- Budget per task: {st.get('maxSteps', 12)} steps / {2 * st.get('maxSteps', 12)} student calls (binding), "
          f"{st.get('maxSeconds', 1800)} s wall-clock safety cap", ""]

    # ---- per split summary tables
    for split in SPLITS:
        ids = split_ids.get(split, [])
        rows = []
        for x in exps:
            recs = [r for (s, t), r in x["recs"].items() if s == split and t in ids]
            if recs:
                rows.append(_row(f"{x['id']} {x['label']}", recs, len(ids)))
        if not rows:
            continue
        title = {"heldout": "Held-out (never seen by the teacher)", "gate": "Gate", "train": "Train"}[split]
        L += [f"## {title}: {len(ids)} tasks ({profile} profile)", "",
              "| Harness | Pass | Success [95% CI] | Student calls / task | Prompt tok / task | Output tok / task | Seconds / task | Stop reasons |",
              "|---|---|---|---|---|---|---|---|", *rows, ""]

    # ---- paired comparisons against the reference
    if ref:
        L += [f"## Paired comparisons vs {ref['id']} ({ref['label']})", "",
              "Same tasks, same budget. Δ = other − reference, on per-task mean pass rates (averaged over repetitions). "
              "b = only the reference passes, c = only the other passes, p = exact two-sided McNemar (both on repetition 0).", "",
              "| Split | Harness | n | Δ success [95% CI] | b / c | p | Δ calls / task [95% CI] | Δ seconds / task [95% CI] |",
              "|---|---|---|---|---|---|---|---|"]
        for split in SPLITS:
            ids = set(split_ids.get(split, []))
            a = {t: r for (s, t), r in ref["recs"].items() if s == split and t in ids}
            for x in exps:
                if x is ref:
                    continue
                b = {t: r for (s, t), r in x["recs"].items() if s == split and t in ids}
                common = set(a) & set(b)
                if not common:
                    continue
                d, lo, hi, n = paired_ci({t: float(a[t]["pass"]) for t in common}, {t: float(b[t]["pass"]) for t in common})
                _, oa, ob, _ = discordant({t: a[t]["pass0"] for t in common}, {t: b[t]["pass0"] for t in common})
                dc = paired_ci({t: a[t]["calls"] for t in common}, {t: b[t]["calls"] for t in common})
                ds = paired_ci({t: a[t]["sec"] for t in common}, {t: b[t]["sec"] for t in common})
                L.append(f"| {split} | {x['id']} {x['label']} | {n} | {100 * d:+.0f} pp [{100 * lo:+.0f}, {100 * hi:+.0f}] | "
                         f"{oa} / {ob} | {mcnemar_exact(oa, ob):.2f} | {dc[0]:+.1f} [{dc[1]:+.1f}, {dc[2]:+.1f}] | "
                         f"{ds[0]:+.0f} [{ds[1]:+.0f}, {ds[2]:+.0f}] |")
        L.append("")

    # ---- per-task matrix (held-out first)
    for split in SPLITS:
        ids = split_ids.get(split, [])
        cols = [x for x in exps if any(s == split for s, _ in x["recs"])]
        if not cols:
            continue
        L += [f"### Every {split} task", "", "| Task | Shape | " + " | ".join(x["id"] for x in cols) + " |",
              "|---|---|" + "---|" * len(cols)]
        idx = _index()
        for t in ids:
            cells = []
            for x in cols:
                r = x["recs"].get((split, t))
                if r is None:
                    cells.append("·")
                elif r.get("reps", 1) > 1:
                    cells.append(f"{sum(r['passes'])}/{r['reps']} pass, {r['calls']:.1f}c {r['sec']:.0f}s")
                else:
                    cells.append(f"**pass** {r['calls']:.0f}c {r['sec']:.0f}s" if r["pass"] else
                                 f"fail ({r['label']}) {r['calls']:.0f}c {r['sec']:.0f}s")
            L.append(f"| `{t}` | {idx.get(t, {}).get('bugShape', '?')} | " + " | ".join(cells) + " |")
        L.append("")

    # ---- failure labels
    L += ["## Why tasks failed (labeller: `tasks/labels.py`)", "",
          "`process` = never reached / edited the root cause, looped, never verified; `knowledge` = right place, wrong fix; "
          "`format` = could not drive the tools; `budget` = the wall-clock cap cut a live model call (not attributable to the model).", "",
          "| Harness | split | process | knowledge | format | budget |", "|---|---|---|---|---|---|"]
    for x in exps:
        for split in SPLITS:
            labs = Counter(r["label"] for (s, _, _), r in x["runs"].items() if s == split and not r["pass"])
            if labs:
                L.append(f"| {x['id']} | {split} | {labs.get('process', 0)} | {labs.get('knowledge', 0)} | "
                         f"{labs.get('format', 0)} | {labs.get('budget', 0)} |")
    L.append("")

    # ---- growth runs
    for g in cfg.get("growth", []):
        p = ROOT / g["log"]
        if p.exists():
            L += render_growth(g, read_events(p))

    # ---- Warden + execution
    L += ["## Warden at run time", "", "| Harness | executor | blocks |", "|---|---|---|"]
    for x in exps:
        ex = x["start"].get("executor") if x["start"].get("mode") != "baseline" else "n/a (no routines; tool subprocesses in bwrap)"
        L.append(f"| {x['id']} | {ex} | "
                 f"{sum(1 for e in x['events'] if e['type'] == 'warden.block')} |")
    L.append("")

    # ---- automatic notes
    notes = []
    for x in exps:
        n_t = sum(1 for r in x["runs"].values() if r["stop"] in ("TaskTimeout", "timeout"))
        if n_t:
            notes.append(f"{x['id']}: {n_t} task(s) hit the {st.get('maxSeconds', 1800)} s safety cap.")
        n_c = sum(1 for r in x["runs"].values() if r["cached"])
        if n_c:
            notes.append(f"{x['id']}: {n_c} task outcome(s) replayed from the round-0 cache (same config key).")
    if notes:
        L += ["## Notes (computed)", "", *[f"- {n}" for n in notes], ""]
    return "\n".join(L) + "\n"


def render_growth(g: dict, ev: list[dict]) -> list[str]:
    start = _start(ev)
    cfgd = start.get("config") or {}
    steps = [e for e in ev if e["type"] == "growth.step"]
    props = {e.get("step"): e for e in ev if e["type"] == "growth.proposal"}
    repairs = {e.get("step"): e for e in ev if e["type"] == "growth.repair"}
    gates = {e.get("round"): e for e in ev if e["type"] == "gate.result"}
    end = next((e for e in reversed(ev) if e["type"] == "run.end"), None)
    teacher = [e for e in ev if e["type"] == "model.call" and e.get("role") == "teacher"]
    L = [f"## Growth: {g['id']} {g['label']}", "",
         f"Algorithm: paper failure window. K={cfgd.get('k')}, R_max={cfgd.get('r_max')}, Q={cfgd.get('q')}, "
         f"L={cfgd.get('budget')}, ablations: {', '.join(cfgd.get('ablate') or []) or 'none'}. "
         f"Status: {'finished: ' + str(end['summary'].get('stopReason')) if end else 'in progress'}.", "",
         "| Step | Changes | d_fun | Window re-run | Gate | Outcome |", "|---|---|---|---|---|---|"]
    for s in steps:
        t = s.get("step")
        pr, rp, gt = props.get(t, {}), repairs.get(t), gates.get(t)
        rep = f"{len(rp['solved'])}/{len(rp['solved']) + len(rp['unsolved'])}" if rp else "–"
        gate = f"{gt['gateBefore']} → {gt['gateAfter']}/{gt.get('gateTotal')}" if gt else "–"
        out = "**accepted**" if s["outcome"] == "accepted" else f"rejected at {s['stage']}"
        L.append(f"| {t} | {', '.join(s.get('changes') or []) or '–'} | {pr.get('dFun', '–')} | {rep} | {gate} | {out} |")
    L.append("")
    for s in steps:
        pr = props.get(s.get("step"))
        if pr:
            L.append(f"- **step {s['step']}** ({s['outcome']}): {pr.get('rationale', '')[:900]}")
            if s["outcome"] != "accepted":
                L.append(f"  - rejected: {s.get('reason', '')[:300]}")
    cost = sum(e.get("costUsd") or 0 for e in teacher)
    L += ["", f"Teacher: {len(teacher)} calls, {sum(e.get('promptTokens') or 0 for e in teacher):,} prompt tokens "
              f"({sum(e.get('cacheHitTokens') or 0 for e in teacher):,} cache hits), "
              f"{sum(e.get('outTokens') or 0 for e in teacher):,} output tokens, **${cost:.4f}** "
              f"({sum(1 for e in teacher if e.get('peak'))} calls at peak prices).", ""]
    if end:
        sm = end["summary"]
        L += [f"Final harness h{sm.get('finalHarness')} (`{sm.get('registry')}`); retired without repair: "
              f"{', '.join(sm.get('retired') or []) or 'none'}; solved on first sight: {', '.join(sm.get('solvedOnFill') or []) or 'none'}.", ""]
    return L


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args(argv)
    cfg = json.loads(a.config.read_text())
    text = render(cfg, a.config)
    if a.out:
        a.out.write_text(text)
        print(f"wrote {a.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
