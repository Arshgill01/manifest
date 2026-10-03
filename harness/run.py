"""Harness entry point (CONTRACT 2.3).

    run_task(workdir, mode="baseline"|"manifest", log=log) -> {steps, modelCalls, routineCalls, selfReportedDone, stopReason}

Emits routine.call / model.call / tool.call / warden.block only; task.start/task.end belong to the runner
(growth/eval.py). The CLI below is for standalone runs and emits the full run/task envelope itself:

    uv run python -m harness.run <taskdir> --mode baseline|manifest [--registry routines/registry.json]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator, Literal

from harness.controller import Controller, Executor, load_registry
from harness.log import ROOT, EventLog, new_run_id
from harness.loop import run_baseline
from harness.state import State
from harness.student import Student, TaskStop, TaskTimeout
from harness.tools import Tools

CALLS_PER_STEP = 2  # student call budget = max_steps * this (an ask may re-ask once)


@contextlib.contextmanager
def wall_clock(seconds: float) -> Iterator[None]:
    """Raise TaskTimeout in the main thread after `seconds` (interrupts a stuck routine or a slow model
    call). Off the main thread, limits fall back to deadline checks between calls."""
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        yield
        return

    def fire(signum, frame):
        raise TaskTimeout(f"wall-clock limit of {seconds:.0f}s reached")

    old = signal.signal(signal.SIGALRM, fire)
    signal.setitimer(signal.ITIMER_REAL, max(0.01, seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def run_task(workdir: Path, *, mode: Literal["baseline", "manifest"], log: EventLog,
             registry: str | None = None, max_steps: int = 12, max_seconds: int = 120,
             executor: Executor | None = None, student: Any = None) -> dict:
    workdir = Path(workdir).resolve()
    if mode not in ("baseline", "manifest"):
        raise ValueError(f"mode must be 'baseline' or 'manifest', not {mode!r}")
    deadline = time.monotonic() + max_seconds
    student = student if student is not None else Student(log)
    calls0 = getattr(student, "calls", 0)
    student.deadline = deadline
    student.max_calls = calls0 + max_steps * CALLS_PER_STEP

    result: dict[str, Any] = {"steps": 0, "routineCalls": 0, "selfReportedDone": False, "stopReason": ""}
    controller = None
    state = None
    try:
        with wall_clock(max_seconds + 0.5):  # grace: let the deadline checks win when they can
            if mode == "baseline":
                tools = Tools(workdir, None, log, skill="baseline", deadline=deadline)
                task = (workdir / "TASK.md").read_text(encoding="utf-8") if (workdir / "TASK.md").is_file() else \
                    "The test suite is failing. Make it pass without editing tests."
                out = run_baseline(tools, student, task=task, max_steps=max_steps, deadline=deadline)
                result.update(steps=out["steps"], selfReportedDone=out["selfReportedDone"], stopReason=out["stopReason"])
            else:
                controller = Controller(load_registry(registry), student, log, executor=executor,
                                        max_steps=max_steps, deadline=deadline)
                state = controller.run(State(task_dir=str(workdir), max_steps=max_steps))
    except TaskStop as e:  # timer fired between the loop's own checks
        result["stopReason"] = type(e).__name__
    if controller is not None:
        result.update(steps=state.steps if state else controller.routine_calls, routineCalls=controller.routine_calls,
                      selfReportedDone=bool(state and state.done),
                      stopReason=result["stopReason"] or controller.stop_reason)
    result["modelCalls"] = getattr(student, "calls", 0) - calls0
    student.deadline = None
    student.max_calls = None
    return result


# ---- CLI -------------------------------------------------------------------------------------------

def _task_meta(task_id: str) -> dict:
    index = ROOT / "tasks" / "index.json"
    if index.is_file():
        return json.loads(index.read_text(encoding="utf-8")).get(task_id, {})
    return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m harness.run", description="Run the harness on one task dir.")
    ap.add_argument("taskdir", type=Path)
    ap.add_argument("--mode", choices=["baseline", "manifest"], default="baseline")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--max-seconds", type=int, default=120)
    ap.add_argument("--label", default=None, help="run-file label (default: run-<mode>)")
    ap.add_argument("--in-place", action="store_true", help="edit the task dir itself instead of a copy")
    a = ap.parse_args(argv)

    src = a.taskdir.resolve()
    if not src.is_dir():
        ap.error(f"{src} is not a directory")
    task_id = src.name
    log = EventLog.create(a.label or f"run-{a.mode}")
    if a.in_place:
        workdir = src
    else:
        workdir = ROOT / ".manifest" / "work" / (log.run_id or new_run_id("run")) / task_id
        shutil.copytree(src, workdir, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))

    student = Student(log)
    log.emit("run.start", mode=a.mode, student=student.model, teacher=None, online=False)
    meta = _task_meta(task_id)
    with log.scope(taskId=task_id, split=None):
        log.emit("task.start", domain=meta.get("domain"), bugShape=meta.get("bugShape"), mode=a.mode)
        t0 = time.monotonic()
        res = run_task(workdir, mode=a.mode, log=log, registry=a.registry, max_steps=a.max_steps,
                       max_seconds=a.max_seconds, student=student)
        ms = int((time.monotonic() - t0) * 1000)
        final = Tools(workdir).run_tests()  # unlogged judge run
        passed = bool(final["ok"])
        log.emit("task.end", **{"pass": passed}, steps=res["steps"], modelCalls=res["modelCalls"],
                 routineCalls=res["routineCalls"], ms=ms, stopReason=res["stopReason"])
    log.emit("run.end", summary={"pass": passed, **res, "workdir": str(workdir)})
    print(json.dumps({"pass": passed, **res, "ms": ms, "final": f"{final['failed']} failed, {final['passed']} passed",
                      "log": str(log.path), "workdir": str(workdir)}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
