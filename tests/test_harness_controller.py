"""Controller: registry order, first-applies, executor protocol, crash isolation, wall clock."""

import json
from pathlib import Path

import pytest

from harness.controller import DEFAULT_MANIFEST, DEFAULT_REGISTRY, Controller, Executor, InProcessExecutor, load_registry
from harness.fakes import ScriptedStudent
from harness.log import EventLog
from harness.run import run_task
from harness.smoke import make_package
from harness.state import State


@pytest.fixture
def pkg(tmp_path):
    return make_package(tmp_path / "pkg")


def routine(tmp_path: Path, name: str, applies: str, body: str, manifest: dict | None = None) -> dict:
    d = tmp_path / "routines" / name
    d.mkdir(parents=True)
    (d / "routine.py").write_text(
        f"NAME = {name!r}\n"
        f"def applies(state):\n    return {applies}\n"
        f"def run(state, tools, student):\n" + "".join(f"    {l}\n" for l in body.splitlines()) + "    return state\n")
    if manifest is not None:
        (d / "manifest.json").write_text(json.dumps(manifest))
    return {"name": name, "path": str(d), "source": "grown"}


def registry(tmp_path, *grown) -> str:
    p = tmp_path / "registry.json"
    p.write_text(json.dumps([{"name": "start", "path": "routines/seed/start", "source": "seed"}, *grown,
                             {"name": "ask-student", "path": "routines/seed/ask-student", "source": "seed"}]))
    return str(p)


def test_repo_registry_is_well_formed():
    """The live registry: seeds bracket it (start first, ask-student fallback last); everything between is grown."""
    from harness.controller import ROOT
    entries = json.loads((ROOT / "routines" / "registry.json").read_text())
    names = [e["name"] for e in entries]
    assert names[0] == "start" and names[-1] == "ask-student"
    assert all(e["source"] == "grown" and (ROOT / e["path"] / "routine.py").exists() for e in entries[1:-1])
    specs = load_registry()  # seed-only in tests (conftest pins it)
    assert specs[-1].manifest["write"] == ["src/**"] and specs[0].manifest["write"] == []


def test_missing_manifest_gets_grown_default(tmp_path):
    r = routine(tmp_path, "x", "False", "pass")
    spec = load_registry(registry(tmp_path, r))[1]
    assert spec.manifest == DEFAULT_MANIFEST and spec.source == "grown"


def test_first_applying_routine_wins_and_can_finish(pkg, tmp_path):
    fix = routine(tmp_path, "fixer", "state.routine_runs.get('start')",
                  "tools.edit_file('src/tinyledger/money.py', 'rounding=ROUND_DOWN', 'rounding=ROUND_HALF_UP')\n"
                  "r = tools.run_tests()\n"
                  "state.last_full_run = {'passed': r['passed'], 'failed': r['failed']}\n"
                  "state.done = r['ok']\n"
                  "state.summary = 'patched rounding'")
    never = routine(tmp_path, "never", "True", "raise AssertionError('should not run')")
    log = EventLog()
    student = ScriptedStudent([])
    res = run_task(pkg, mode="manifest", log=log, registry=registry(tmp_path, fix, never), student=student)
    calls = [e for e in log.events if e["type"] == "routine.call"]
    assert [c["routine"] for c in calls] == ["start", "fixer"]
    assert calls[1]["summary"] == "patched rounding" and calls[1]["source"] == "grown"
    assert res == {"steps": 2, "routineCalls": 2, "selfReportedDone": True, "stopReason": "done", "modelCalls": 0}
    tool_skills = {e["skill"] for e in log.events if e["type"] == "tool.call"}
    assert tool_skills == {"start", "fixer"}


def test_routine_manifest_enforced(pkg, tmp_path):
    sneaky = routine(tmp_path, "sneaky", "not state.notes.get('tried')",
                     "state.notes['tried'] = True\n"
                     "tools.edit_file('tests/test_money.py', '1200', '1')",
                     manifest=DEFAULT_MANIFEST)
    log = EventLog()
    run_task(pkg, mode="manifest", log=log, registry=registry(tmp_path, sneaky), student=ScriptedStudent([]))
    block = next(e for e in log.events if e["type"] == "warden.block")
    assert block["skill"] == "sneaky" and "tests/test_money.py" in block["attempted"]
    call = next(e for e in log.events if e["type"] == "routine.call" and e["routine"] == "sneaky")
    assert call["ok"] is False and "WardenBlock" in call["summary"]
    assert "1200" in (pkg / "tests/test_money.py").read_text()


def test_crashing_routine_rolled_back_and_disabled_after_two(pkg, tmp_path):
    boom = routine(tmp_path, "boom", "True", "state.suspect = {'file': 'half-written'}\nraise RuntimeError('kaput')")
    log = EventLog()
    student = ScriptedStudent(["done"])
    res = run_task(pkg, mode="manifest", log=log, registry=registry(tmp_path, boom), student=student)
    calls = [(e["routine"], e["ok"]) for e in log.events if e["type"] == "routine.call"]
    assert calls == [("start", True), ("boom", False), ("boom", False), ("ask-student", True)]
    assert res["selfReportedDone"] and res["steps"] == 4
    # crashed runs left no half-applied state behind: ask-student's digest shows no suspect
    assert "half-written" not in json.dumps(student.seen[0]["messages"])


def test_broken_trigger_is_skipped(pkg, tmp_path):
    bad = routine(tmp_path, "badtrigger", "1 / 0", "pass")
    log = EventLog()
    res = run_task(pkg, mode="manifest", log=log, registry=registry(tmp_path, bad), student=ScriptedStudent(["done"]))
    assert res["selfReportedDone"]
    assert any("applies() raised ZeroDivisionError" in e["summary"] for e in log.events if e["type"] == "routine.call")


def test_custom_executor_protocol(pkg):
    seen = []

    class Recording:
        def run(self, routine_dir, state, tools, student, manifest):
            seen.append((Path(routine_dir).name, type(state).__name__, tools.skill, manifest["write"]))
            return InProcessExecutor().run(routine_dir, state, tools, student, manifest)

    assert isinstance(Recording(), Executor)
    run_task(pkg, mode="manifest", log=EventLog(), executor=Recording(), student=ScriptedStudent(["done"]))
    assert seen == [("start", "State", "start", []), ("ask-student", "State", "ask-student", ["src/**"])]


def test_executor_may_return_new_state_from_json(pkg):
    """Out-of-process executors hand back a deserialised State; the controller must accept it."""

    class RoundTrip:
        def run(self, routine_dir, state, tools, student, manifest):
            out = InProcessExecutor().run(routine_dir, State.from_json(state.to_json()), tools, student, manifest)
            return State.from_json(out.to_json())

    res = run_task(pkg, mode="manifest", log=EventLog(), executor=RoundTrip(),
                   student=ScriptedStudent([{"tool": "run_tests"}, "done"]))
    assert res["selfReportedDone"] and res["modelCalls"] == 2


def test_wall_clock_kills_stuck_routine(pkg, tmp_path):
    stuck = routine(tmp_path, "stuck", "True", "while True:\n    pass")
    log = EventLog()
    res = run_task(pkg, mode="manifest", log=log, registry=registry(tmp_path, stuck),
                   student=ScriptedStudent([]), max_seconds=1)
    assert res["stopReason"] == "TaskTimeout" and not res["selfReportedDone"]
    last = [e for e in log.events if e["type"] == "routine.call"][-1]
    assert last["routine"] == "stuck" and "task limit" in last["summary"]


def test_state_roundtrip_with_extra_fields():
    s = State(task_dir="/x", failures=[{"test": "t", "error": "e", "frames": [{"file": "a", "line": 1, "function": "f"}]}])
    s.rollback_count = 2  # grown routines may add their own fields
    back = State.from_json(s.to_json())
    assert back.failures == s.failures and back.rollback_count == 2 and back.steps_left == 12


def test_controller_stops_when_nothing_applies(pkg, tmp_path):
    reg = tmp_path / "r.json"
    reg.write_text(json.dumps([{"name": "start", "path": "routines/seed/start", "source": "seed"}]))
    c = Controller(load_registry(reg), ScriptedStudent([]), EventLog())
    state = c.run(State(task_dir=str(pkg)))
    assert c.stop_reason == "no_routine_applies" and state.steps == 1 and state.task.startswith("The test suite")


def test_dangerous_verdict_never_runs(pkg, tmp_path):
    evil = routine(tmp_path, "evil", "True", "raise AssertionError('must not run')",
                   manifest={**DEFAULT_MANIFEST, "verdict": "dangerous"})
    log = EventLog()
    run_task(pkg, mode="manifest", log=log, registry=registry(tmp_path, evil), student=ScriptedStudent(["done"]))
    assert "evil" not in [e["routine"] for e in log.events if e["type"] == "routine.call"]
