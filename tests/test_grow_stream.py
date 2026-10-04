"""v2 growth (growth/stream.py + growth/validate.py): constraints, rollback, resume, no held-out leakage."""

import json

import pytest

from growth import stubs
from growth.stream import Stream, StreamConfig
from growth.validate import banned_terms, check_changeset, fn_diff
from harness.teacher import FAKE_PROPOSALS, FakeTeacher, TeacherError

BASE = '''NAME = "fix"
LIMIT = 3

def _helper(x):
    return x + 1

def applies(state):
    return not state.done

def run(state, tools, student):
    return state
'''


def change(src, name="fix"):
    return {"name": name, "trigger_description": "t", "routine_py": src, "skill_md": "---\nname: x\n---\n"}


def test_fn_diff_counts_functions_and_module_code():
    new = BASE.replace("return x + 1", "return x + 2").replace("LIMIT = 3", "LIMIT = 4")
    d = fn_diff(BASE, new)
    assert d["modified"] == ["_helper"] and d["other"] and not d["removed"]
    assert fn_diff(None, BASE)["added"] == ["_helper", "applies", "run"]


def test_deletion_scope_budget_and_specificity():
    cur = {"fix": BASE}
    no_helper = BASE.replace("def _helper(x):\n    return x + 1\n\n", "")
    v = check_changeset([change(no_helper)], cur, scope={"fix"}, budget=10, banned=[])
    assert not v.ok and "deleted" in v.reason
    body = BASE.replace("return state\n", "state.done = True\n    return state\n")
    v = check_changeset([change(body)], cur, scope=set(), budget=10, banned=[])
    assert not v.ok and "did not run" in v.reason
    trig = BASE.replace("return not state.done", "return not state.done and state.steps < 5")
    assert check_changeset([change(trig)], cur, scope=set(), budget=10, banned=[]).ok   # trigger-only is the dispatcher
    v = check_changeset([change(BASE.replace('NAME = "fix"', 'NAME = "other"'), "other")], cur, scope=set(), budget=2, banned=[])
    assert not v.ok and "edit budget" in v.reason   # a new routine costs its 3 functions
    v = check_changeset([change(body.replace("x + 1", "x + 1  # money.py"))], cur, scope={"fix"}, budget=10,
                        banned=banned_terms())
    assert not v.ok and "money" in v.reason
    v = check_changeset([change(body)], cur, scope={"fix"}, budget=10, banned=[], order=[])
    assert not v.ok and "order" in v.reason


def test_hackathon_routine_passes_the_lint():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "routines/grown/triage-fix/routine.py").read_text()
    v = check_changeset([change(src, "triage-fix")], {}, scope=set(), budget=20, banned=banned_terms())
    assert v.ok, v.reason


def _stream(tmp_path, teacher=None, **kw):
    cfg = StreamConfig(fake_teacher=True, stub_runner=True, max_opt_steps=kw.pop("steps", 6), **kw)
    s = Stream(cfg, teacher=teacher, root=tmp_path)
    return s


def test_rehearsal_rollback_and_versions(tmp_path):
    s = _stream(tmp_path)
    summary = s.loop()
    events = s.log.events
    steps = [e for e in events if e["type"] == "growth.step"]
    assert any(e["outcome"] == "rejected" and e["stage"] == "warden" for e in steps)   # fetch-hints
    accepted = [e for e in steps if e["outcome"] == "accepted"]
    assert summary["finalHarness"] == len(accepted)
    # every rejection left the harness version untouched (transactional rollback)
    for e in steps:
        if e["outcome"] == "rejected":
            assert e["harness"] == max([a["harness"] for a in accepted if a["step"] < e["step"]], default=0)
    for k in range(summary["finalHarness"] + 1):
        assert (s.hdir / f"h{k}.json").exists()
    assert json.loads((s.hdir / "registry.json").read_text()) == s.entries()
    # held-out ran exactly once, at the end, with the final harness
    held = [e for e in events if e["type"] == "eval.heldout"]
    assert len(held) == 1 and summary["heldout"]["harness"] == summary["finalHarness"]


def test_teacher_never_sees_heldout(tmp_path):
    s = _stream(tmp_path)
    s.loop()
    blob = json.dumps(s.teacher.prompts)
    for tid in stubs.STUB_SPLITS["heldout"]:
        assert tid not in blob
    assert "csvflow" not in blob


class FlakyTeacher(FakeTeacher):
    """Goes down at the second proposal (API outage)."""

    def propose_changes(self, context, check=None):
        if self.calls >= 1 and not getattr(self, "recovered", False):
            raise TeacherError("API down")
        return super().propose_changes(context, check)


def test_resume_after_teacher_outage(tmp_path):
    s = _stream(tmp_path, teacher=FlakyTeacher(None, FAKE_PROPOSALS[2:3] + FAKE_PROPOSALS[3:]))
    out = s.loop()
    assert "teacher unavailable" in out["stopReason"]
    ck = json.loads(s.ckpt_path.read_text())
    assert not ck["done"] and ck["step"] >= 1
    t2 = FakeTeacher(None, FAKE_PROPOSALS[3:])
    s2 = Stream(StreamConfig(**{**ck["config"], "max_opt_steps": 4}), teacher=t2, root=tmp_path, resume=s.run_id)
    out2 = s2.loop()
    assert out2["steps"] > ck["step"] and s2.state["done"]
    assert s2.log.path == s.log.path  # one log per growth run, appended on resume


def test_window_one_ablation_sets_k(tmp_path):
    s = _stream(tmp_path, ablate=["window-1"], steps=2)
    s.loop()
    windows = [e for e in s.log.events if e["type"] == "growth.window"]
    assert windows and all(len(w["window"]) <= 1 for w in windows)
