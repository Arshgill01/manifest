"""RoutedExecutor: seeds in-process, teacher-written routines (run + applies) in the kernel sandbox, with
function-level fn.call/fn.return events either way."""

import json
from pathlib import Path

import pytest

from harness.fakes import ScriptedStudent
from harness.log import EventLog
from harness.run import run_task
from harness.smoke import make_package
from warden import sandbox

pytestmark = pytest.mark.skipif(not sandbox.sandbox_available(), reason="needs a kernel sandbox")

GROWN = '''
NAME = "fixer"

def _target(state):
    return "src/tinyledger/money.py"

def _patch(tools, path):
    return tools.edit_file(path, "rounding=ROUND_DOWN", "rounding=ROUND_HALF_UP")

def applies(state):
    try:
        open("tests/sneaky.py", "w").write("x = 1\\n")   # must be refused even inside applies()
    except OSError:
        pass
    return state.routine_runs.get("start", 0) > 0 and not state.done

def run(state, tools, student):
    _patch(tools, _target(state))
    r = tools.run_tests()
    state.done = r["ok"]
    state.summary = "patched"
    return state
'''


def test_grown_routine_runs_sandboxed_with_fn_trace(tmp_path):
    pkg = make_package(tmp_path / "pkg")
    d = tmp_path / "grown" / "fixer"
    d.mkdir(parents=True)
    (d / "routine.py").write_text(GROWN)
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps([{"name": "start", "path": "routines/seed/start", "source": "seed"},
                               {"name": "fixer", "path": str(d), "source": "grown"},
                               {"name": "ask-student", "path": "routines/seed/ask-student", "source": "seed"}]))
    log = EventLog()
    ex = sandbox.make_executor("sandbox", log)
    res = run_task(pkg, mode="manifest", log=log, registry=str(reg), student=ScriptedStudent([]), executor=ex)
    assert res["selfReportedDone"] and res["stopReason"] == "done"
    assert not (pkg / "tests" / "sneaky.py").exists()
    fns = [(e["fn"], e["depth"]) for e in log.events if e["type"] == "fn.call" and e["routine"] == "fixer"]
    assert fns == [("run", 0), ("_target", 1), ("_patch", 1)]  # args are evaluated before the call
    assert any(e["type"] == "fn.call" and e["routine"] == "start" for e in log.events)  # seeds traced in-process
    rets = [e for e in log.events if e["type"] == "fn.return" and e["fn"] == "_target"]
    assert rets and rets[0]["ret"] == "'src/tinyledger/money.py'"
    assert any(e["type"] == "warden.block" and "sneaky" in e["attempted"] for e in log.events)
    assert ex.describe().startswith("seed:inprocess, grown:sandbox:")
