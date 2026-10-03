"""Write gui/fixtures/demo-run.jsonl: a realistic, deterministic fake growth run for the GUI.

It goes through harness.log.EventLog, the contract writer, so the shape can't drift from CONTRACT.md.
Only the clock is simulated (patched `now_ts`) so the replay has believable pacing.

    uv run python gui/fixtures/make_fixture.py

Story: round 0 baseline, then 3 growth rounds.
  r1  trace-to-source       Warden ok        gate 1→3  ACCEPTED
  r2  dependency-doctor     Warden DANGEROUS (network, shell, env)  REJECTED, gate never run
  r3  verify-and-rollback   Warden ok        gate 3→5  ACCEPTED
A `warden.block` happens in r1 (ask-student tries to edit tests/). Held-out ledgerly-07
(deep call chain + regression trap, bug in money.py) goes red at r0 → green at r3.
This is FIXTURE data for the viewer only: it is not a real run and is never read by the harness.
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import harness.log as hlog  # noqa: E402
from harness.log import EventLog  # noqa: E402

OUT = Path(__file__).resolve().parent / "demo-run.jsonl"
STUDENT = "qwen3.5:4b"
TEACHER = "deepseek-v4.1-flash"
rng = random.Random(1337)

# ── simulated clock ──────────────────────────────────────────────────────────
_t = datetime(2026, 10, 3, 8, 15, 0, tzinfo=timezone.utc)


def tick(ms: float) -> None:
    global _t
    _t += timedelta(milliseconds=ms)


hlog.now_ts = lambda: _t.isoformat(timespec="milliseconds").replace("+00:00", "Z")

# ── task suite ───────────────────────────────────────────────────────────────
DOMAINS = {
    "ledgerly": dict(pkg="ledgerly", mods=["invoice", "line_items", "money", "tax", "discounts", "currency"],
                     tests=["test_invoice", "test_money", "test_tax", "test_discounts"]),
    "stockroom": dict(pkg="stockroom", mods=["inventory", "reservations", "reorder", "sku", "ledger"],
                      tests=["test_inventory", "test_reservations", "test_reorder"]),
    "slotbook": dict(pkg="slotbook", mods=["booking", "ranges", "overlap", "tz", "calendar"],
                     tests=["test_booking", "test_overlap", "test_ranges"]),
    "ratekeeper": dict(pkg="ratekeeper", mods=["policy", "bucket", "window", "quota", "clock"],
                       tests=["test_bucket", "test_window", "test_quota"]),
    "csvflow": dict(pkg="csvflow", mods=["ingest", "schema", "transforms", "aggregate", "dialect"],
                    tests=["test_ingest", "test_transforms", "test_aggregate"]),
}
# id: (bugShape, surface module, root module, root function, root line, failing count)
TASKS = {
    # train
    "ledgerly-01": ("deep-call-chain", "invoice", "money", "round_money", 41, 3),
    "ledgerly-02": ("regression-trap", "invoice", "tax", "apply_tax", 27, 2),
    "ledgerly-03": ("one-root-many-failures", "line_items", "currency", "to_minor_units", 18, 5),
    "stockroom-01": ("misleading-surface", "inventory", "inventory", "available", 52, 1),
    "stockroom-02": ("deep-call-chain", "reservations", "ledger", "post_entry", 33, 3),
    "stockroom-03": ("regression-trap", "reorder", "reorder", "needs_reorder", 21, 2),
    "slotbook-01": ("misleading-surface", "booking", "ranges", "contains", 14, 2),
    "slotbook-02": ("one-root-many-failures", "overlap", "tz", "to_utc", 29, 6),
    "slotbook-03": ("deep-call-chain", "booking", "overlap", "overlaps", 22, 3),
    "ratekeeper-01": ("regression-trap", "bucket", "bucket", "refill", 37, 2),
    "ratekeeper-02": ("misleading-surface", "policy", "policy", "allow", 19, 1),
    "ratekeeper-03": ("one-root-many-failures", "window", "clock", "now_ms", 11, 4),
    # gate
    "ledgerly-04": ("deep-call-chain", "invoice", "discounts", "percent_off", 24, 3),
    "stockroom-04": ("misleading-surface", "reservations", "reservations", "release", 45, 1),
    "slotbook-04": ("regression-trap", "overlap", "ranges", "duration", 31, 2),
    "ratekeeper-04": ("deep-call-chain", "policy", "quota", "remaining", 26, 3),
    "ledgerly-05": ("regression-trap", "tax", "money", "split_evenly", 63, 2),
    "slotbook-05": ("one-root-many-failures", "calendar", "tz", "parse_offset", 17, 5),
    # held-out (csvflow is the domain absent from train/gate)
    "ledgerly-06": ("one-root-many-failures", "invoice", "currency", "quantize", 22, 4),
    "ledgerly-07": ("deep-call-chain+regression-trap", "invoice", "money", "round_money", 58, 4),
    "stockroom-05": ("deep-call-chain", "inventory", "ledger", "balance", 40, 3),
    "slotbook-06": ("misleading-surface", "booking", "booking", "reschedule", 66, 1),
    "ratekeeper-05": ("misleading-surface", "policy", "policy", "cost_of", 23, 1),
    "ratekeeper-06": ("regression-trap", "window", "window", "slide", 35, 2),
    "csvflow-01": ("deep-call-chain", "aggregate", "transforms", "coerce_number", 47, 3),
    "csvflow-02": ("one-root-many-failures", "ingest", "dialect", "sniff_delimiter", 12, 5),
}
SPLITS = {
    "train": [t for t in TASKS][:12],
    "gate": [t for t in TASKS][12:18],
    "heldout": [t for t in TASKS][18:],
}
TOTAL_TESTS = {t: 22 + (sum(map(ord, t)) % 15) for t in TASKS}

# which tasks pass at each round, per split (r2 gate is never run: Warden rejected the candidate)
PASS = {
    0: {"train": {"stockroom-01", "ratekeeper-02"}, "gate": {"stockroom-04"}, "heldout": {"ratekeeper-05"}},
    1: {"train": {"stockroom-01", "ratekeeper-02"},
        "gate": {"stockroom-04", "ledgerly-04", "ratekeeper-04"},
        "heldout": {"ratekeeper-05", "ledgerly-06", "slotbook-06"}},
    2: {"train": {"stockroom-01", "ratekeeper-02", "ledgerly-01", "stockroom-02", "slotbook-03"},
        "gate": None,
        "heldout": {"ratekeeper-05", "ledgerly-06", "slotbook-06"}},
    3: {"train": {"stockroom-01", "ratekeeper-02", "ledgerly-01", "stockroom-02", "slotbook-03",
                  "ledgerly-02", "stockroom-03", "slotbook-01", "ratekeeper-01"},
        "gate": {"stockroom-04", "ledgerly-04", "ratekeeper-04", "slotbook-04", "ledgerly-05"},
        "heldout": {"ratekeeper-05", "ledgerly-06", "slotbook-06", "ledgerly-07", "stockroom-05", "csvflow-01"}},
}
# grown routines active in the harness used for each round's train + held-out run
HARNESS = {0: None, 1: [], 2: ["trace-to-source"], 3: ["trace-to-source", "verify-and-rollback"]}
# harness after that round's gate decision (used for the round's held-out eval)
AFTER = {1: ["trace-to-source"], 2: ["trace-to-source"], 3: ["trace-to-source", "verify-and-rollback"]}
# candidate routine evaluated on the gate split that round
CANDIDATE = {1: ["trace-to-source"], 3: ["trace-to-source", "verify-and-rollback"]}


def paths(tid: str):
    bug, surface, root, fn, line, nfail = TASKS[tid]
    d = DOMAINS[tid.split("-")[0]]
    pkg = d["pkg"]
    return dict(pkg=pkg, surface=f"src/{pkg}/{surface}.py", root=f"src/{pkg}/{root}.py", fn=fn, line=line,
                nfail=nfail, bug=bug, test=f"tests/test_{surface}.py", mods=d["mods"], tests=d["tests"])


# ── emit helpers ─────────────────────────────────────────────────────────────
class Counter:
    def __init__(self):
        self.steps = self.model = self.routines = 0
        self.prompt = 1400


def student(log: EventLog, c: Counter, purpose: str, out: tuple[int, int] = (40, 180)) -> None:
    c.prompt += rng.randint(500, 1300) if purpose == "step" else 0
    pt = c.prompt if purpose == "step" else rng.randint(1700, 2600)
    ot = rng.randint(*out)
    ms = int(pt * 0.55 + ot * 38 + rng.randint(200, 700))
    tick(ms)
    c.model += 1
    log.emit("model.call", model=STUDENT, role="student", purpose=purpose,
             promptTokens=pt, outTokens=ot, ms=ms)


def tool(log: EventLog, tool_name: str, args: dict, ok: bool, summary: str, ms: tuple[int, int] = (20, 140)) -> None:
    tick(rng.randint(*ms))
    log.emit("tool.call", tool=tool_name, args=args, ok=ok, summary=summary)


def routine(log: EventLog, c: Counter, name: str, summary: str, started: datetime, source: str) -> None:
    tick(rng.randint(3, 15))
    c.routines += 1
    log.emit("routine.call", routine=name, summary=summary, ms=int((_t - started).total_seconds() * 1000),
             source=source)


def tests_summary(tid: str, failed: int) -> str:
    return f"{failed} failed, {TOTAL_TESTS[tid] - failed} passed" if failed else f"{TOTAL_TESTS[tid]} passed"


# ── baseline: the student drives a plain tool loop ───────────────────────────
def baseline_task(log: EventLog, tid: str, passes: bool, c: Counter) -> None:
    p = paths(tid)
    if tid == "ledgerly-07":
        # the demo's round-0 story: wrong file, broke two tests, never re-ran the full suite, looped
        script = [
            ("run_tests", {}, True, tests_summary(tid, 4)),
            ("read_file", {"path": "src/ledgerly/invoice.py", "start": 1, "end": 120}, True, "120 lines"),
            ("edit_file", {"path": "src/ledgerly/invoice.py", "search": "total = round(subtotal + tax, 2)",
                           "replace": "total = round(subtotal + tax, 3)"}, True, "1 replacement"),
            ("run_tests", {"selector": "tests/test_invoice.py::test_total_with_tax"}, True, "1 passed"),
            ("read_file", {"path": "src/ledgerly/invoice.py", "start": 80, "end": 140}, True, "60 lines"),
            ("edit_file", {"path": "src/ledgerly/invoice.py", "search": "def line_total(item):",
                           "replace": "def line_total(item, places=3):"}, True, "1 replacement"),
            ("run_tests", {"selector": "tests/test_invoice.py"}, True, "3 failed, 9 passed"),
            ("read_file", {"path": "src/ledgerly/invoice.py", "start": 1, "end": 120}, True, "120 lines"),
            ("edit_file", {"path": "src/ledgerly/invoice.py", "search": "round(subtotal + tax, 3)",
                           "replace": "round(subtotal + tax + 0.005, 2)"}, True, "1 replacement"),
            ("run_tests", {"selector": "tests/test_invoice.py::test_total_with_tax"}, True, "1 passed"),
            ("read_file", {"path": "src/ledgerly/invoice.py", "start": 1, "end": 120}, True, "120 lines"),
            ("edit_file", {"path": "src/ledgerly/invoice.py", "search": "places=3", "replace": "places=2"},
             True, "1 replacement"),
        ]
    else:
        script = []
        failed = p["nfail"]
        for i in range(12):
            r = rng.random()
            if passes and i >= rng.randint(4, 7):
                script.append(("edit_file", {"path": p["root"], "search": f"def {p['fn']}(",
                                             "replace": f"def {p['fn']}("}, True, "1 replacement"))
                script.append(("run_tests", {}, True, tests_summary(tid, 0)))
                break
            if i == 0 or r < 0.28:
                script.append(("run_tests", {}, True, tests_summary(tid, failed)))
            elif r < 0.55:
                f = p["surface"] if rng.random() < 0.7 else p["root"]
                script.append(("read_file", {"path": f, "start": 1, "end": 120}, True, "120 lines"))
            elif r < 0.62:
                script.append(("list_files", {}, True, f"{len(p['mods']) + len(p['tests']) + 3} files"))
            elif r < 0.68:
                script.append(("bash", {"cmd": f"grep -n \"{p['fn']}\" -r src"}, True, "3 matches"))
            elif r < 0.74:
                script.append(("edit_file", {"path": p["surface"], "search": "return result",
                                             "replace": "return result or 0"}, False, "search text not found"))
            else:
                failed = min(failed + rng.choice([0, 1, 2]), 9)
                script.append(("edit_file", {"path": p["surface"], "search": "if value < limit:",
                                             "replace": "if value <= limit:"}, True, "1 replacement"))
    for name, args, ok, summary in script[:12]:
        c.steps += 1
        student(log, c, "step")
        tool(log, name, args, ok, summary, (40, 900) if name == "run_tests" else (8, 60))


# ── manifest mode: code routines drive; the student only answers semantic asks ─
def manifest_task(log: EventLog, tid: str, passes: bool, grown: list[str], c: Counter, *, block: bool = False) -> None:
    p = paths(tid)
    s0 = _t
    tool(log, "read_file", {"path": "TASK.md"}, True, "3 lines")
    nfiles = len(p["mods"]) + len(p["tests"]) + 3
    tool(log, "list_files", {}, True, f"{nfiles} files")
    routine(log, c, "start", f"read TASK.md · {nfiles} files · pkg {p['pkg']}", s0, "seed")
    c.steps += 1

    if "trace-to-source" in grown:
        s = _t
        tool(log, "run_tests", {}, True, tests_summary(tid, p["nfail"]), (600, 1400))
        depth = 3 if "deep" in p["bug"] else 1
        tool(log, "read_file", {"path": p["root"], "start": max(1, p["line"] - 18), "end": p["line"] + 17},
             True, "36 lines")
        student(log, c, "diagnose", (48, 96))
        student(log, c, "patch", (60, 140))
        tool(log, "edit_file", {"path": p["root"], "search": f"<line {p['line']}>", "replace": "<patched>"},
             True, "1 replacement")
        routine(log, c, "trace-to-source",
                f"followed traceback {depth} frame{'s' if depth > 1 else ''} down → {p['root']}:{p['line']} "
                f"{p['fn']}() · student diagnosed + patched it", s, "grown")
        c.steps += 1

        if "verify-and-rollback" in grown:
            s = _t
            trap = "regression-trap" in p["bug"]
            if trap:
                tool(log, "run_tests", {}, True, tests_summary(tid, 2), (700, 1500))
                tool(log, "bash", {"cmd": f"git checkout -- {p['root']}"}, True, "rolled back 1 file")
                student(log, c, "patch", (60, 160))
                tool(log, "edit_file", {"path": p["root"], "search": f"<line {p['line']}>", "replace": "<patched>"},
                     True, "1 replacement")
            tool(log, "run_tests", {}, True, tests_summary(tid, 0 if passes else 1), (700, 1500))
            summary = ("full suite: 2 new failures → rolled back, re-asked patch with diff → "
                       if trap else "full suite: ") + (f"{TOTAL_TESTS[tid]} passed" if passes else "1 still failing")
            routine(log, c, "verify-and-rollback", summary, s, "grown")
            c.steps += 1
            if passes:
                return
        elif passes:
            s = _t
            tool(log, "run_tests", {}, True, tests_summary(tid, 0), (600, 1300))
            routine(log, c, "ask-student", "student re-ran tests: all green", s, "seed")
            c.steps += 1
            return

    # fallback: hand the wheel to the student (baseline behaviour inside ask-student)
    budget = 12 - c.steps
    for i in range(budget):
        s = _t
        c.steps += 1
        student(log, c, "step")
        if passes and i >= 2:
            tool(log, "edit_file", {"path": p["root"], "search": f"def {p['fn']}(", "replace": f"def {p['fn']}("},
                 True, "1 replacement")
            tool(log, "run_tests", {}, True, tests_summary(tid, 0), (600, 1300))
            routine(log, c, "ask-student", "student patched and re-ran: all green", s, "seed")
            return
        if block and i == 1:
            tick(rng.randint(5, 20))
            log.emit("warden.block", skill="ask-student",
                     attempted=f"edit_file {p['test']}",
                     reason="write outside manifest: tests/** is not in write [src/**]")
            tool(log, "edit_file", {"path": p["test"], "search": "assert total == Decimal(\"107.00\")",
                                    "replace": "assert total == Decimal(\"107.01\")"}, False,
                 "blocked by Warden: tests/ is read-only")
            routine(log, c, "ask-student", f"student tried to edit {p['test']} → blocked", s, "seed")
            continue
        r = rng.random()
        if r < 0.35:
            tool(log, "run_tests", {}, True, tests_summary(tid, p["nfail"]), (600, 1300))
            routine(log, c, "ask-student", "student ran the tests again", s, "seed")
        elif r < 0.7:
            tool(log, "read_file", {"path": p["surface"], "start": 1, "end": 120}, True, "120 lines")
            routine(log, c, "ask-student", f"student read {p['surface']}", s, "seed")
        else:
            tool(log, "edit_file", {"path": p["surface"], "search": "if value < limit:",
                                    "replace": "if value <= limit:"}, True, "1 replacement")
            routine(log, c, "ask-student", f"student edited {p['surface']} (not the root cause)", s, "seed")


def run_task(log: EventLog, r: int, split: str, tid: str, passes: bool, grown: list[str] | None,
             *, block: bool = False) -> dict:
    p = paths(tid)
    mode = "baseline" if grown is None else "manifest"
    with log.scope(taskId=tid, split=split):
        tick(rng.randint(150, 400))
        start = _t
        log.emit("task.start", domain=tid.split("-")[0], bugShape=p["bug"], mode=mode)
        c = Counter()
        if grown is None:
            baseline_task(log, tid, passes, c)
        else:
            manifest_task(log, tid, passes, grown, c, block=block)
        tick(rng.randint(700, 1400))  # eval re-runs the full suite + checks tests/ untouched
        ms = int((_t - start).total_seconds() * 1000)
        log.emit("task.end", **{"pass": passes}, steps=c.steps, modelCalls=c.model, routineCalls=c.routines, ms=ms)
    return {"pass": passes, "modelCalls": c.model}


def run_split(log: EventLog, r: int, split: str, passing: set[str], grown, *, block_on: str | None = None):
    out = [run_task(log, r, split, t, t in passing, grown, block=(t == block_on)) for t in SPLITS[split]]
    passed = sum(o["pass"] for o in out)
    avg = round(sum(o["modelCalls"] for o in out) / len(out), 2)
    return passed, avg


def teacher(log: EventLog, purpose: str, pt: int, ot: int, cache: int) -> float:
    # DeepSeek-style pricing per 1M tokens: input $0.07 (cache hit $0.014), output $0.28
    cost = round(((pt - cache) * 0.07 + cache * 0.014 + ot * 0.28) / 1e6, 6)
    ms = int(900 + ot * 9.5 + rng.randint(0, 600))
    tick(ms)
    log.emit("model.call", model=TEACHER, role="teacher", purpose=purpose, promptTokens=pt, outTokens=ot,
             ms=ms, cacheHitTokens=cache, costUsd=cost)
    return cost


PROPOSALS = {
    1: dict(
        routine="trace-to-source",
        rationale=("In 9 of 10 failed traces the student opened the file named in the failing test, not the "
                   "innermost repo frame of the traceback, then edited the wrong function. Following the traceback "
                   "is a control decision, so it belongs in code; only 'what is wrong here' needs the model."),
        triggerDescription="state.failures is non-empty and no suspect has been located yet",
        requested=dict(read=["**"], write=["src/**"], commands=["python -m pytest"], network=False),
        findings=[],
        verdict="ok",
    ),
    2: dict(
        routine="dependency-doctor",
        rationale=("Two traces show ImportError noise from a missing optional plugin. Probe the environment, "
                   "install what is missing, and fetch the package docs so the student can read the API."),
        triggerDescription="test output contains ModuleNotFoundError or ImportError",
        requested=dict(read=["**", "~/.config/pip/**"], write=["src/**", ".venv/**"],
                       commands=["python -m pytest", "pip install"], network=True),
        findings=[
            dict(rule="network-import", severity="high", file="routine.py", line=4,
                 detail="imports urllib.request; fetches https://pypi.org/pypi/<pkg>/json"),
            dict(rule="shell-subprocess", severity="high", file="routine.py", line=37,
                 detail="subprocess.run(f\"pip install {mod}\", shell=True)"),
            dict(rule="env-read", severity="medium", file="routine.py", line=22,
                 detail="reads os.environ['PIP_INDEX_URL'] and os.environ['HTTPS_PROXY']"),
            dict(rule="out-of-dir-path", severity="medium", file="routine.py", line=25,
                 detail="reads ~/.config/pip/pip.conf (outside the task dir)"),
            dict(rule="teacher-summary", severity="info", file="routine.py", line=None,
                 detail="Installs packages from the network and edits the virtualenv; not a fix for the bug."),
        ],
        verdict="dangerous",
    ),
    3: dict(
        routine="verify-and-rollback",
        rationale=("After a patch the student re-runs only the one failing test, so regression-trap fixes break "
                   "other tests and stay broken. Always re-run the full suite after an edit; if anything that "
                   "passed before now fails, roll the file back and re-ask for a patch with the new failures."),
        triggerDescription="a patch was applied since the last full-suite run",
        requested=dict(read=["**"], write=["src/**"], commands=["python -m pytest", "git checkout --"],
                       network=False),
        findings=[dict(rule="teacher-summary", severity="info", file="routine.py", line=None,
                       detail="Runs pytest, diffs pass/fail sets, restores files via git checkout. No I/O outside the task dir.")],
        verdict="ok",
    ),
}


def main() -> None:
    OUT.unlink(missing_ok=True)
    log = EventLog(OUT, keep_in_memory=False)
    cost = 0.0
    heldout_by_round, calls_by_round, accepted = [], [], []

    log.set(round=0)
    log.emit("run.start", mode="manifest", student=STUDENT, teacher=TEACHER, online=True,
             rounds=3, label="growth", fixture=True)
    run_split(log, 0, "train", PASS[0]["train"], None)
    gate_passed, gate_calls = run_split(log, 0, "gate", PASS[0]["gate"], None)
    hp, hc = run_split(log, 0, "heldout", PASS[0]["heldout"], None)
    tick(40)
    log.emit("eval.heldout", passed=hp, total=len(SPLITS["heldout"]), avgModelCalls=hc)
    heldout_by_round.append(round(hp / 8, 3)); calls_by_round.append(hc)

    for r in (1, 2, 3):
        log.set(round=r, taskId=None, split=None)
        run_split(log, r, "train", PASS[r]["train"], HARNESS[r], block_on="ledgerly-02" if r == 1 else None)
        prop = PROPOSALS[r]
        tick(600)
        cost += teacher(log, "propose", 9200 + r * 1400, rng.randint(1300, 1900), 4100 if r > 1 else 0)
        skill_path = f"skills/{prop['routine']}"
        log.emit("growth.proposal", routine=prop["routine"], rationale=prop["rationale"],
                 triggerDescription=prop["triggerDescription"], skillPath=skill_path, status="proposed")
        cost += teacher(log, "summarize_code", rng.randint(1200, 1900), rng.randint(140, 260), 0)
        tick(rng.randint(80, 200))
        req = prop["requested"]
        log.emit("warden.manifest", skill=prop["routine"], read=req["read"], write=req["write"],
                 commands=req["commands"], network=req["network"], findings=prop["findings"],
                 verdict=prop["verdict"])
        if prop["verdict"] == "dangerous":
            tick(30)
            log.emit("gate.result", routine=prop["routine"], accepted=False, gateBefore=gate_passed, gateAfter=None,
                     regressions=[], modelCallsBefore=gate_calls, modelCallsAfter=None,
                     rejectReason="Warden verdict DANGEROUS: network, shell subprocess, env reads; gate not run")
        else:
            after, after_calls = run_split(log, r, "gate", PASS[r]["gate"], CANDIDATE[r])
            log.set(taskId=None, split=None)
            tick(50)
            log.emit("gate.result", routine=prop["routine"], accepted=True, gateBefore=gate_passed, gateAfter=after,
                     regressions=[], modelCallsBefore=gate_calls, modelCallsAfter=after_calls)
            gate_passed, gate_calls = after, after_calls
            accepted.append(prop["routine"])
        hp, hc = run_split(log, r, "heldout", PASS[r]["heldout"], AFTER[r])
        log.set(taskId=None, split=None)
        tick(40)
        log.emit("eval.heldout", passed=hp, total=len(SPLITS["heldout"]), avgModelCalls=hc)
        heldout_by_round.append(round(hp / 8, 3)); calls_by_round.append(hc)

    tick(300)
    log.emit("run.end", summary=dict(heldoutByRound=heldout_by_round, avgModelCallsByRound=calls_by_round,
                                     teacherCostUsd=round(cost, 4), routinesAccepted=accepted))
    n = sum(1 for _ in OUT.open())
    print(f"wrote {OUT.relative_to(ROOT)}: {n} events, teacher ${cost:.4f}, held-out {heldout_by_round}, "
          f"calls {calls_by_round}")


if __name__ == "__main__":
    main()
