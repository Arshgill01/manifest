"""Run a harness over a task split and judge every task independently (CONTRACT 2.2).

    uv run python -m growth.eval --split train --mode baseline --round 0
    uv run python -m growth.eval --split heldout --mode manifest --round 2 --registry routines/registry.json
    uv run python -m growth.eval --split train,gate,heldout --mode oracle     # self-test, no model

The harness never judges itself. After it returns, the runner re-runs the real test suite in the
task's working copy and checks that no test-side file was touched or added. Only then is a task
counted as passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from harness.log import ROOT, EventLog
from tasks.gen import IGNORE, apply_edits, run_pytest
from tasks.mutations import Edit

TASKS = ROOT / "tasks"
GENERATED = TASKS / "generated"
WORK = ROOT / ".manifest" / "work"
CACHE = ROOT / ".manifest" / "cache"
FAKEHOME = ROOT / "demo" / "fakehome"

STUDENT = os.environ.get("STUDENT_MODEL", "qwen3.5:4b")
TEACHER = os.environ.get("TEACHER_MODEL") or "deepseek-v4.1-flash"
HARNESS_MODES = ("baseline", "manifest")
SELFTEST_MODES = ("oracle", "noop")   # runner self-tests: apply the reference fix / do nothing

# Files that decide what "the tests pass" means. Any change or addition => automatic fail.
PROTECTED_NAMES = {"conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini",
                   "sitecustomize.py", "usercustomize.py"}


# ---------------------------------------------------------------- task metadata

def load_index() -> dict[str, dict]:
    return json.loads((TASKS / "index.json").read_text())


def load_splits(profile: str = "core") -> dict[str, list[str]]:
    data = json.loads((TASKS / "splits.json").read_text())
    return data["profiles"][profile]


def task_ids_for(split: str, profile: str = "core") -> list[str]:
    return list(load_splits(profile)[split])


# ---------------------------------------------------------------- integrity

def protected_fingerprint(task_dir: Path) -> dict[str, str]:
    """Hash of every test-side file: tests/**, any conftest/pytest config, any .pth file."""
    out: dict[str, str] = {}
    for p in sorted(task_dir.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        rel = p.relative_to(task_dir).as_posix()
        if rel.startswith("tests/") or p.name in PROTECTED_NAMES or p.suffix == ".pth":
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def judge(work: Path, pristine: Path, expected_total: int) -> dict[str, Any]:
    before = protected_fingerprint(pristine)
    after = protected_fingerprint(work)
    tampered = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    try:
        result = run_pytest(work, timeout=90)
        passed, failed = len(result.passed), len(result.failed)
    except Exception as exc:  # timeout, crash
        passed, failed = 0, expected_total
        tampered = tampered or []
        return {"pass": False, "passed": 0, "failed": failed, "expected": expected_total,
                "testsUntouched": not tampered, "tampered": tampered, "error": f"judge: {exc}"}
    ok = not tampered and failed == 0 and passed == expected_total
    return {"pass": ok, "passed": passed, "failed": failed, "expected": expected_total,
            "testsUntouched": not tampered, "tampered": tampered}


# ---------------------------------------------------------------- environment

@contextmanager
def task_env():
    """HOME -> demo/fakehome and no bytecode for the duration of a task (SPEC §6.3)."""
    FAKEHOME.mkdir(parents=True, exist_ok=True)
    saved = {k: os.environ.get(k) for k in ("HOME", "PYTHONDONTWRITEBYTECODE")}
    os.environ["HOME"] = str(FAKEHOME)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def is_online(timeout: float = 0.7) -> bool:
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=timeout).close()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- running

def _run_selftest(mode: str, work: Path, meta: dict) -> dict:
    if mode == "oracle":
        apply_edits(work, tuple(Edit(**e) for e in meta["fix"]))
    return {"steps": 0, "modelCalls": 0, "routineCalls": 0, "selfReportedDone": mode == "oracle"}


def run_one(task_id: str, *, split: str | None, mode: str, round: int, log: EventLog,
            registry: str | None, run_dir: Path, max_steps: int, max_seconds: int,
            executor=None) -> dict:
    index = load_index()
    meta = index[task_id]
    pristine = GENERATED / task_id
    work = run_dir / task_id
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(pristine, work, ignore=IGNORE)
    expected_total = len(meta["failingTests"]) + meta["passingTests"]

    with log.scope(round=round, taskId=task_id, split=split):
        start_idx = len(log.events or [])
        log.emit("task.start", domain=meta["domain"], bugShape=meta["bugShape"], mode=mode)
        t0 = time.monotonic()
        error = None
        stats: dict[str, Any] = {"steps": 0, "modelCalls": 0, "routineCalls": 0}
        with task_env():
            try:
                if mode in SELFTEST_MODES:
                    stats = _run_selftest(mode, work, meta)
                else:
                    from harness.run import run_task  # track B

                    stats = run_task(work, mode=mode, log=log, registry=registry,
                                     max_steps=max_steps, max_seconds=max_seconds, executor=executor) or stats
            except Exception as exc:  # a crashing harness is a failed task, not a crashed eval
                error = f"{type(exc).__name__}: {exc}"
            verdict = judge(work, pristine, expected_total)
        ms = int((time.monotonic() - t0) * 1000)
        end = log.emit(
            "task.end",
            **{"pass": verdict["pass"]},
            steps=stats.get("steps", 0),
            modelCalls=stats.get("modelCalls", 0),
            routineCalls=stats.get("routineCalls", 0),
            ms=ms,
            judge=verdict,
            selfReportedDone=stats.get("selfReportedDone"),
            stopReason=stats.get("stopReason"),
            overtime=ms > (max_seconds + 30) * 1000,
            **({"error": error} if error else {}),
        )
        events = (log.events or [])[start_idx:]
    return {
        "taskId": task_id, "pass": end["pass"], "steps": end["steps"], "modelCalls": end["modelCalls"],
        "routineCalls": end["routineCalls"], "ms": ms, "judge": verdict, "error": error,
        "events": [e for e in events if e.get("taskId") == task_id],
    }


def run_split(split: str, *, mode: str, round: int, log: EventLog, registry: str | None = None,
              task_ids: list[str] | None = None, profile: str = "core", max_steps: int = 12,
              max_seconds: int = 120, executor=None, use_cache: bool = True) -> dict:
    """Run `mode` over a split. Round-0 baseline results are cached and replayed, never recomputed."""
    ids = list(task_ids or task_ids_for(split, profile))
    # keyed on the exact task list, so callers passing explicit ids (growth loop) still hit it
    key = hashlib.sha256(",".join(ids).encode()).hexdigest()[:10]
    cache_file = CACHE / f"round0-{split}-{key}.json"
    cacheable = mode == "baseline" and round == 0
    if cacheable and use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text())
        for outcome in cached["results"]:
            for e in outcome["events"]:
                _replay(log, e)
        if split == "heldout":
            log.emit("eval.heldout", round=round, taskId=None, split=split, passed=cached["passed"],
                     total=cached["total"], avgModelCalls=cached["avgModelCalls"], cached=True)
        return cached

    run_dir = WORK / (log.run_id or f"adhoc-{int(time.time())}") / f"r{round}-{split}"
    results = [
        run_one(tid, split=split, mode=mode, round=round, log=log, registry=registry, run_dir=run_dir,
                max_steps=max_steps, max_seconds=max_seconds, executor=executor)
        for tid in ids
    ]
    passed = sum(r["pass"] for r in results)
    out = {
        "split": split, "mode": mode, "round": round, "profile": profile,
        "passed": passed, "total": len(results),
        "avgModelCalls": round_(sum(r["modelCalls"] for r in results) / max(len(results), 1)),
        "results": results,
    }
    if split == "heldout":
        log.emit("eval.heldout", round=round, taskId=None, split=split, passed=passed,
                 total=len(results), avgModelCalls=out["avgModelCalls"])
    if cacheable:
        CACHE.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(out, default=str))
    return out


def round_(x: float) -> float:
    return round(x, 2)


def _replay(log: EventLog, event: dict) -> None:
    fields = {k: v for k, v in event.items() if k not in ("ts", "type")}
    with log.scope(round=fields.pop("round", 0), taskId=fields.pop("taskId", None), split=fields.pop("split", None)):
        log.emit(event["type"], **fields, cached=True)


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="train", help="train|gate|heldout, comma-separated for several")
    ap.add_argument("--mode", default="baseline", choices=HARNESS_MODES + SELFTEST_MODES)
    ap.add_argument("--round", type=int, default=0)
    ap.add_argument("--profile", default="core", help="any profile in tasks/splits.json: core, full, demo")
    ap.add_argument("--tasks", help="comma-separated task ids (overrides the split's list)")
    ap.add_argument("--limit", type=int, help="only the first N tasks of each split")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--max-seconds", type=int, default=120)
    ap.add_argument("--force", action="store_true", help="ignore the round-0 cache")
    ap.add_argument("--label", default=None)
    args = ap.parse_args(argv)
    known = json.loads((TASKS / "splits.json").read_text())["profiles"]
    if args.profile not in known:
        ap.error(f"unknown profile {args.profile!r}; choose from {', '.join(known)}")

    label = args.label or f"eval-{args.mode}-r{args.round}"
    log = EventLog.create(label, round=args.round)
    log.emit("run.start", mode=args.mode, student=STUDENT, teacher=TEACHER, online=is_online(),
             profile=args.profile)
    summary = {}
    for split in args.split.split(","):
        ids = args.tasks.split(",") if args.tasks else task_ids_for(split, args.profile)
        if args.limit:
            ids = ids[: args.limit]
        explicit = ids if (args.tasks or args.limit) else None
        res = run_split(split, mode=args.mode, round=args.round, log=log, registry=args.registry,
                        task_ids=explicit, profile=args.profile, max_steps=args.max_steps,
                        max_seconds=args.max_seconds, use_cache=not args.force)
        summary[split] = {"passed": res["passed"], "total": res["total"], "avgModelCalls": res["avgModelCalls"]}
        print(f"\n{split}: {res['passed']}/{res['total']} passed, avg model calls {res['avgModelCalls']}")
        for r in res["results"]:
            j = r["judge"]
            flag = "PASS" if r["pass"] else "fail"
            extra = f" tampered={j['tampered']}" if j.get("tampered") else ""
            extra += f" error={r['error']}" if r.get("error") else ""
            print(f"  {flag} {r['taskId']:14} tests {j['passed']}/{j['expected']}  steps {r['steps']:2}  "
                  f"calls {r['modelCalls']:2}  {r['ms'] / 1000:6.1f}s{extra}")
    log.emit("run.end", round=args.round, taskId=None, split=None, summary=summary)
    print(f"\nevents → {log.path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
