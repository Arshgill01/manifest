from growth.gate import as_split_result, decide, reject_before_gate, run_gate
from harness.log import EventLog


def split(passing: dict[str, bool], calls: float) -> dict:
    results = [{"taskId": t, "pass": p, "modelCalls": calls} for t, p in passing.items()]
    return {"split": "gate", "passed": sum(passing.values()), "total": len(results), "avgModelCalls": calls, "results": results}


def test_improvement_accepted():
    d = decide(split({"a": False, "b": True}, 8), split({"a": True, "b": True}, 8))
    assert d.accepted and d.gateBefore == 1 and d.gateAfter == 2 and not d.regressions


def test_flat_with_big_call_drop_accepted():
    assert decide(split({"a": True, "b": False}, 10), split({"a": True, "b": False}, 8)).accepted  # exactly 20%


def test_flat_with_small_call_drop_rejected():
    d = decide(split({"a": True, "b": False}, 10), split({"a": True, "b": False}, 8.5))
    assert not d.accepted and "15%" in d.rejectReason


def test_improvement_with_regression_rejected():
    d = decide(split({"a": True, "b": False, "c": False}, 8), split({"a": False, "b": True, "c": True}, 4))
    assert not d.accepted and d.regressions == ["a"]


def test_decrease_rejected():
    assert not decide(split({"a": True, "b": True}, 8), split({"a": True, "b": False}, 2)).accepted


def test_zero_calls_before_does_not_divide():
    assert not decide(split({"a": False}, 0), split({"a": False}, 0)).accepted


def test_normalises_objects():
    from pydantic import BaseModel

    class R(BaseModel):
        taskId: str
        pass_: bool
        modelCalls: int

    class S(BaseModel):
        split: str
        results: list[R]

    s = as_split_result(S(split="gate", results=[R(taskId="a", pass_=True, modelCalls=4)]))
    assert s["passed"] == 1 and s["total"] == 1 and s["avgModelCalls"] == 4 and s["results"][0]["pass"] is True


def test_run_gate_emits_event():
    log = EventLog()
    before = split({"a": False, "b": False}, 6)
    calls = []

    def fake_run_split(name, **kw):
        calls.append((name, kw))
        return split({"a": True, "b": False}, 6)

    d, after = run_gate(routine="r", registry="reg.json", before=before, run_split=fake_run_split, log=log, round=2, task_ids=["a", "b"])
    assert d.accepted
    assert calls == [("gate", {"mode": "manifest", "round": 2, "log": log, "registry": "reg.json", "task_ids": ["a", "b"]})]
    ev = log.events[-1]
    assert ev["type"] == "gate.result" and ev["split"] == "gate"
    for k in ("routine", "accepted", "gateBefore", "gateAfter", "regressions", "modelCallsBefore", "modelCallsAfter"):
        assert k in ev


def test_reject_before_gate_logs():
    log = EventLog()
    d = reject_before_gate(log, "evil", split({"a": True}, 5), "warden verdict: dangerous")
    assert not d.accepted and log.events[-1]["gateAfter"] is None and log.events[-1]["rejectReason"].startswith("warden")
