"""Held-out leak tests (CONTRACT 2.5): no held-out id or content may reach any teacher prompt."""

import json
from types import SimpleNamespace

import pytest

from growth import stubs
from growth.grow import GrowConfig, LeakError, assert_no_leak, banned_terms, grow
from harness.log import EventLog
from harness.teacher import FAKE_PROPOSALS, FakeTeacher, Prices, Teacher

SPLITS = dict(stubs.STUB_SPLITS)
HELDOUT = SPLITS["heldout"]
SENTINEL = "HELDOUT-SECRET-CONTENT"


def leaky_run_split(split, **kw):
    """The stub runner, plus loud held-out-only content in every held-out event."""
    res = stubs.run_split(split, **kw)
    if split == "heldout":
        log = kw["log"]
        for r in res["results"]:
            with log.scope(taskId=r["taskId"], split="heldout"):
                r["events"].append(log.emit("tool.call", tool="read_file", args={"path": "src/x.py"}, ok=True,
                                            summary=f"{SENTINEL} def secret_{r['taskId'].replace('-', '_')}(): ..."))
    return res


class RoutingClient:
    """OpenAI-shaped client: proposals for propose calls, findings for Warden summaries. Records every request."""

    def __init__(self):
        self.requests = []
        self._i = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        if "security reviewer" in kw["messages"][0]["content"]:
            content = json.dumps({"findings": ["drives harness tools only"]})
        else:
            content = json.dumps(FAKE_PROPOSALS[self._i % len(FAKE_PROPOSALS)])
            self._i += 1
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10))


def run(tmp_path, teacher, run_split=leaky_run_split):
    cfg = GrowConfig(stub_runner=True, splits=SPLITS, scratch_root=tmp_path, log_path=tmp_path / "run.jsonl",
                     round0="all", heldout_every_round=True)
    return grow(cfg, teacher=teacher, run_split=run_split, warden=(stubs.warden_scan, stubs.warden_build))


def test_no_heldout_in_any_teacher_prompt(tmp_path):
    client = RoutingClient()
    teacher = Teacher(EventLog(), client=client, model="deepseek-test", prices=Prices())
    s = run(tmp_path, teacher)
    assert s["roundsRun"] == 4 and len(s["heldoutByRound"]) == 5  # held-out really ran every round

    sent = [json.dumps(r["messages"]) for r in client.requests]
    assert sum("Growth round" in p for p in sent) == 4
    for prompt in sent:
        assert SENTINEL not in prompt
        for tid in HELDOUT:
            assert tid not in prompt, f"held-out id {tid} leaked into a teacher prompt"
        assert SPLITS["novelDomain"] not in prompt
    # sanity: the train traces really are in there
    assert any(tid in p for tid in SPLITS["train"] for p in sent)


def test_heldout_outcomes_do_not_change_teacher_prompts(tmp_path):
    def flipped(split, **kw):
        res = leaky_run_split(split, **kw)
        if split == "heldout":
            for r in res["results"]:
                r["pass"] = not r["pass"]
            res["passed"] = sum(r["pass"] for r in res["results"])
        return res

    a, b = FakeTeacher(EventLog()), FakeTeacher(EventLog())
    run(tmp_path / "a", a)
    run(tmp_path / "b", b, run_split=flipped)
    assert a.prompts == b.prompts


def test_guard_blocks_heldout_smuggled_into_train(tmp_path):
    def smuggling(split, **kw):
        res = stubs.run_split(split, **kw)
        if split == "train":
            for r in res["results"]:
                r["events"].append({"type": "tool.call", "taskId": r["taskId"], "split": "train", "tool": "bash",
                                    "args": {}, "ok": True, "summary": f"see also {HELDOUT[0]}"})
        return res

    teacher = FakeTeacher(EventLog())
    with pytest.raises(LeakError):
        run(tmp_path, teacher, run_split=smuggling)
    assert teacher.prompts == []


def test_banned_terms_and_guard():
    terms = banned_terms(SPLITS)
    assert set(HELDOUT) <= set(terms) and "csvflow" in terms
    assert_no_leak({"x": "ledgerly-01 failed"}, terms)  # train id is fine
    with pytest.raises(LeakError):
        assert_no_leak({"x": f"task {HELDOUT[0]}"}, terms)
    with pytest.raises(LeakError):
        assert_no_leak({"x": "import csvflow.schema"}, terms)
