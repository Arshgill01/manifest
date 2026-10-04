"""Controller mode (SPEC 4.2, CONTRACT 2.4): code drives a State through routines from the registry.

Loop: pick the first routine (registry order) whose `applies(state)` is true, run it through the
executor with Tools bound to that routine's manifest, repeat until `state.done` or limits hit.
Each run is one step and logs `routine.call`.
"""

from __future__ import annotations

import importlib.util
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, runtime_checkable

from harness.log import ROOT, EventLog
from harness.state import State
from harness.student import TaskStop
from harness.tools import Tools

DEFAULT_REGISTRY = ROOT / "routines" / "registry.json"
MAX_ROUTINE_ERRORS = 2  # a routine that raises this many times in one task is skipped for the rest of it

# Warden's default for grown routines (SPEC 6.2); used when a routine dir has no manifest.json
DEFAULT_MANIFEST = {"read": ["**"], "write": ["src/**"], "commands": ["python -m pytest"], "network": False}


@runtime_checkable
class Executor(Protocol):
    def run(self, routine_dir: Path, state: State, tools: Tools, student: Any, manifest: dict) -> State: ...


@dataclass
class RoutineSpec:
    name: str
    path: Path            # routine dir (holds routine.py, maybe manifest.json, SKILL.md)
    source: str = "seed"  # "seed" | "grown"
    manifest: dict = field(default_factory=dict)


def load_registry(registry: str | Path | None = None) -> list[RoutineSpec]:
    path = Path(registry) if registry else DEFAULT_REGISTRY
    entries = json.loads(path.read_text(encoding="utf-8"))
    specs = []
    for e in entries:
        rdir = Path(e["path"])
        rdir = rdir if rdir.is_absolute() else ROOT / rdir
        if not (rdir / "routine.py").is_file():
            raise FileNotFoundError(f"registry entry {e['name']!r}: no routine.py in {rdir}")
        mf = rdir / "manifest.json"
        manifest = json.loads(mf.read_text(encoding="utf-8")) if mf.is_file() else dict(DEFAULT_MANIFEST)
        specs.append(RoutineSpec(e["name"], rdir, e.get("source", "seed"), manifest))
    return specs


_MODULES: dict[tuple[str, float], ModuleType] = {}


def load_routine(routine_dir: Path) -> ModuleType:
    """Import routine.py from a dir (cached by path + mtime). Dirs like `ask-student` aren't packages."""
    file = Path(routine_dir) / "routine.py"
    key = (str(file.resolve()), file.stat().st_mtime)
    if key not in _MODULES:
        name = "manifest_routine_" + "".join(c if c.isalnum() else "_" for c in Path(routine_dir).name)
        spec = importlib.util.spec_from_file_location(name, file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        for attr in ("applies", "run"):
            if not callable(getattr(mod, attr, None)):
                raise TypeError(f"{file}: missing {attr}(state, ...)")
        _MODULES[key] = mod
    return _MODULES[key]


def fresh_routine(routine_dir: Path) -> ModuleType:
    """Import routine.py uncached (so per-run instrumentation never leaks into another task)."""
    file = Path(routine_dir) / "routine.py"
    name = "manifest_routine_run_" + "".join(c if c.isalnum() else "_" for c in Path(routine_dir).name)
    spec = importlib.util.spec_from_file_location(name, file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class InProcessExecutor:
    """Default executor: imports and calls the routine in this process (tool-layer enforcement only).
    Warden's SandboxExecutor runs it in a kernel sandbox instead (warden.sandbox.make_executor)."""

    def __init__(self, trace: bool = True):
        self.trace = trace

    def describe(self) -> str:
        return "inprocess"

    def applies(self, routine_dir: Path, state: State, manifest: dict) -> bool:
        return bool(load_routine(routine_dir).applies(state))

    def run(self, routine_dir: Path, state: State, tools: Tools, student: Any, manifest: dict) -> State:
        log = getattr(tools, "log", None)
        if self.trace and log is not None:
            from harness.fntrace import instrument

            mod = fresh_routine(routine_dir)
            instrument(mod, lambda t, d: log.emit(t, **d), routine=getattr(mod, "NAME", Path(routine_dir).name))
        else:
            mod = load_routine(routine_dir)
        out = mod.run(state, tools, student)
        return out if isinstance(out, State) else state


def _changes(before: State, after: State) -> str:
    """Fallback routine summary: which standard fields the routine changed."""
    parts = []
    if after.last_full_run != before.last_full_run and after.last_full_run:
        parts.append(f"full run {after.last_full_run.get('failed')} failed/{after.last_full_run.get('passed')} passed")
    if len(after.failures) != len(before.failures):
        parts.append(f"failures {len(before.failures)}→{len(after.failures)}")
    if after.suspect != before.suspect and after.suspect:
        s = after.suspect
        parts.append(f"suspect {s.get('file')}:{s.get('line')} {s.get('function') or ''}".rstrip())
    if len(after.patches) != len(before.patches):
        parts.append(f"patches +{len(after.patches) - len(before.patches)}")
    if after.files != before.files:
        parts.append(f"{len(after.files)} files")
    if after.done and not before.done:
        parts.append("done")
    return ", ".join(parts) or "no state change"


class Controller:
    def __init__(self, routines: list[RoutineSpec], student: Any, log: EventLog | None, *,
                 executor: Executor | None = None, max_steps: int = 12, deadline: float | None = None):
        self.routines = routines
        self.student = student
        self.log = log
        self.executor = executor or InProcessExecutor()
        self.max_steps = max_steps
        self.deadline = deadline
        self.routine_calls = 0
        self.stop_reason = ""
        self.errors: dict[str, int] = {}

    def _applies(self, spec: RoutineSpec, state: State) -> bool:
        if self.errors.get(spec.name, 0) >= MAX_ROUTINE_ERRORS or spec.manifest.get("verdict") == "dangerous":
            return False
        check = getattr(self.executor, "applies", None)
        try:
            if check is not None:
                return bool(check(spec.path, state.model_copy(deep=True), spec.manifest))
            return bool(load_routine(spec.path).applies(state.model_copy(deep=True)))
        except Exception as e:  # a broken trigger counts against the routine, never kills the task
            self.errors[spec.name] = self.errors.get(spec.name, 0) + 1
            self._emit(spec, f"applies() raised {type(e).__name__}: {e}", 0, error=True)
            return False

    def pick(self, state: State) -> RoutineSpec | None:
        return next((s for s in self.routines if self._applies(s, state)), None)

    def run(self, state: State) -> State:
        state.max_steps = self.max_steps
        calls0 = getattr(self.student, "calls", 0)
        try:
            while True:
                if state.done:
                    self.stop_reason = "done"; break
                if state.steps >= self.max_steps:
                    self.stop_reason = "max_steps"; break
                if self.deadline is not None and time.monotonic() >= self.deadline:
                    self.stop_reason = "timeout"; break
                spec = self.pick(state)
                if spec is None:
                    self.stop_reason = "no_routine_applies"; break
                state = self._run_one(spec, state, calls0)
        except TaskStop as e:
            self.stop_reason = type(e).__name__
        state.model_calls = getattr(self.student, "calls", 0) - calls0
        return state

    def _run_one(self, spec: RoutineSpec, state: State, calls0: int) -> State:
        tools = Tools(state.task_dir, spec.manifest, self.log, skill=spec.name, deadline=self.deadline)
        before = state.model_copy(deep=True)
        working = state.model_copy(deep=True)  # a routine that crashes mid-way leaves no half-applied state
        working.summary = ""
        t0 = time.monotonic()
        error = False
        try:
            out = self.executor.run(spec.path, working, tools, self.student, spec.manifest)
            new = out if isinstance(out, State) else working
            summary = new.summary or _changes(before, new)
        except TaskStop:
            ms = int((time.monotonic() - t0) * 1000)
            self._finish(spec, state, "stopped: task limit hit", ms)
            raise
        except Exception as e:
            self.errors[spec.name] = self.errors.get(spec.name, 0) + 1
            new, error = before, True
            summary = f"error: {type(e).__name__}: {e}"
        ms = int((time.monotonic() - t0) * 1000)
        self._finish(spec, new, summary, ms, error=error)
        state = new
        state.model_calls = getattr(self.student, "calls", 0) - calls0
        return state

    def _finish(self, spec: RoutineSpec, state: State, summary: str, ms: int, error: bool = False) -> None:
        self.routine_calls += 1
        state.steps += 1
        state.routine_runs[spec.name] = state.routine_runs.get(spec.name, 0) + 1
        state.history.append({"step": state.steps, "routine": spec.name, "summary": summary[:300]})
        state.summary = ""
        self._emit(spec, summary, ms, error=error)

    def _emit(self, spec: RoutineSpec, summary: str, ms: int, error: bool = False) -> None:
        if self.log:
            self.log.emit("routine.call", routine=spec.name, summary=summary[:300], ms=ms,
                          source=spec.source, ok=not error)
