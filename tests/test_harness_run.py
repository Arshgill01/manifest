"""run_task in both modes with a scripted student; baseline loop limits; ask-student state updates."""

import json

import pytest

from harness.fakes import ScriptedStudent
from harness.log import EventLog
from harness.loop import fit
from harness.run import run_task
from harness.smoke import FIX, ROOT_CAUSE, make_package
from harness.tools import Tools

FIXING_SCRIPT = [
    {"tool": "run_tests"},
    {"tool": "read_file", "args": {"path": ROOT_CAUSE["file"], "start": 1, "end": 8}},
    {"tool": "edit_file", "args": {"path": ROOT_CAUSE["file"], "search": FIX[0], "replace": FIX[1]}},
    {"tool": "run_tests"},
    "All tests pass now.",
]


@pytest.fixture
def pkg(tmp_path):
    return make_package(tmp_path / "tinyledger-01")


@pytest.mark.parametrize("mode", ["baseline", "manifest"])
def test_fixing_script_passes(pkg, mode):
    log = EventLog()
    student = ScriptedStudent(list(FIXING_SCRIPT), log=log)
    with log.scope(taskId="tinyledger-01", split="train"):
        res = run_task(pkg, mode=mode, log=log, student=student)
    assert Tools(pkg).run_tests()["ok"]
    assert res["modelCalls"] == 5 and res["selfReportedDone"] is True
    assert set(res) >= {"steps", "modelCalls", "routineCalls", "selfReportedDone"}
    kinds = {e["type"] for e in log.events}
    assert "task.start" not in kinds and "task.end" not in kinds  # the runner owns those
    assert all(e["taskId"] == "tinyledger-01" and e["split"] == "train" for e in log.events)
    if mode == "baseline":
        assert res["steps"] == 5 and res["routineCalls"] == 0 and "routine.call" not in kinds
    else:
        routines = [e["routine"] for e in log.events if e["type"] == "routine.call"]
        assert routines == ["start"] + ["ask-student"] * 5
        assert res["routineCalls"] == res["steps"] == 6
        assert all(e["source"] == "seed" for e in log.events if e["type"] == "routine.call")
    # first student turn sees the task text
    first = student.seen[0]["messages"]
    assert first[0]["role"] == "system" and "test suite is failing" in first[1]["content"]
    json.dumps(log.events)  # every event serialisable


def test_baseline_step_limit(pkg):
    student = ScriptedStudent([{"tool": "list_files"}] * 20)
    res = run_task(pkg, mode="baseline", log=EventLog(), student=student, max_steps=4)
    assert res == {"steps": 4, "routineCalls": 0, "selfReportedDone": False, "stopReason": "max_steps", "modelCalls": 4}


def test_manifest_step_limit_counts_routine_runs(pkg):
    student = ScriptedStudent([{"tool": "list_files"}] * 20)
    res = run_task(pkg, mode="manifest", log=EventLog(), student=student, max_steps=4)
    assert res["steps"] == 4 and res["routineCalls"] == 4 and res["modelCalls"] == 3
    assert res["stopReason"] == "max_steps"


def test_tool_errors_go_back_to_student_not_crash(pkg):
    student = ScriptedStudent([
        {"tool": "read_file", "args": {"path": "../../etc/passwd"}},
        {"tool": "nonsense", "args": {}},
        {"tool": "edit_file", "args": {"path": "tests/test_money.py", "search": "1200", "replace": "1"}},
        {"tool": "read_file", "args": {"path": "src/missing.py"}},
        "giving up",
    ])
    log = EventLog()
    run_task(pkg, mode="manifest", log=log, student=student)
    tool_msgs = [m["content"] for m in student.seen[-1]["messages"] if m["role"] == "tool"]
    assert tool_msgs[0].startswith("BLOCKED by Warden") and "outside the task dir" in tool_msgs[0]
    assert tool_msgs[1].startswith("ERROR: unknown tool")
    assert tool_msgs[2].startswith("BLOCKED by Warden") and "tests/test_money.py" in tool_msgs[2]
    assert tool_msgs[3].startswith("ERROR: no such file")
    assert "1200" in (pkg / "tests/test_money.py").read_text()
    assert sum(e["type"] == "warden.block" for e in log.events) == 2


def test_ask_student_digest_reaches_student(pkg, tmp_path):
    """A (grown-style) routine that sets state fields: ask-student shows them to the student once."""
    rdir = tmp_path / "routines" / "probe"
    rdir.mkdir(parents=True)
    (rdir / "routine.py").write_text(
        "NAME = 'probe'\n"
        "def applies(state):\n    return state.routine_runs.get('start') and not state.routine_runs.get('probe')\n"
        "def run(state, tools, student):\n"
        "    r = tools.run_tests()\n"
        "    state.failures = r['failures']\n"
        "    state.last_full_run = {'passed': r['passed'], 'failed': r['failed']}\n"
        "    state.suspect = {'file': 'src/tinyledger/money.py', 'line': 7, 'function': 'to_cents'}\n"
        "    return state\n")
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps([
        {"name": "start", "path": "routines/seed/start", "source": "seed"},
        {"name": "probe", "path": str(rdir), "source": "grown"},
        {"name": "ask-student", "path": "routines/seed/ask-student", "source": "seed"},
    ]))
    student = ScriptedStudent([{"tool": "list_files"}, "done"])
    log = EventLog()
    res = run_task(pkg, mode="manifest", log=log, registry=str(reg), student=student)
    assert [e["routine"] for e in log.events if e["type"] == "routine.call"] == ["start", "probe", "ask-student", "ask-student"]
    assert "full run 3 failed/3 passed" in [e for e in log.events if e["type"] == "routine.call"][1]["summary"]
    first = student.seen[0]["messages"]
    assert first[-1]["content"].startswith("Harness update:") and "to_cents" in first[-1]["content"]
    second = student.seen[1]["messages"]
    assert sum(m["content"].startswith("Harness update:") for m in second if m["role"] == "user") == 1
    assert res["selfReportedDone"]


def test_fit_elides_old_tool_output():
    msgs = [{"role": "system", "content": "s"}] + [{"role": "tool", "content": "x" * 5000} for _ in range(10)]
    out = fit(msgs, budget=22_000)
    assert sum(len(m["content"]) for m in out) <= 22_000
    assert out[-1]["content"] == "x" * 5000 and msgs[1]["content"] == "x" * 5000  # newest kept; input untouched
