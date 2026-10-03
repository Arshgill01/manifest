"""The GUI's fixture run must obey CONTRACT.md part 1, and tell the story the viewer is built around."""

import json
import re
from pathlib import Path

from harness.log import EVENT_TYPES

FIXTURE = Path(__file__).resolve().parent.parent / "gui" / "fixtures" / "demo-run.jsonl"

REQUIRED = {
    "run.start": {"mode", "student", "teacher", "online"},
    "task.start": {"domain", "bugShape"},
    "task.end": {"pass", "steps", "modelCalls", "routineCalls", "ms"},
    "routine.call": {"routine", "summary", "ms"},
    "model.call": {"model", "role", "purpose", "promptTokens", "outTokens", "ms"},
    "tool.call": {"tool", "args", "ok", "summary"},
    "growth.proposal": {"routine", "rationale", "triggerDescription", "skillPath"},
    "warden.manifest": {"skill", "read", "write", "commands", "network", "findings", "verdict"},
    "warden.block": {"skill", "attempted", "reason"},
    "gate.result": {"routine", "accepted", "gateBefore", "gateAfter", "regressions", "modelCallsBefore",
                    "modelCallsAfter"},
    "eval.heldout": {"passed", "total", "avgModelCalls"},
    "run.end": {"summary"},
}
TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def events():
    return [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]


def test_every_event_matches_contract():
    evs = events()
    assert evs[0]["type"] == "run.start" and evs[-1]["type"] == "run.end"
    last = ""
    for e in evs:
        assert e["type"] in EVENT_TYPES
        assert {"ts", "type", "round", "taskId", "split"} <= e.keys()
        assert TS.match(e["ts"]) and e["ts"] >= last
        last = e["ts"]
        assert isinstance(e["round"], int)
        assert e["split"] in ("train", "gate", "heldout", None)
        assert REQUIRED[e["type"]] <= e.keys(), (e["type"], REQUIRED[e["type"]] - e.keys())
        if e["type"] == "model.call":
            assert e["role"] in ("student", "teacher")


def test_fixture_tells_the_demo_story():
    evs = events()
    assert max(e["round"] for e in evs) == 3
    gates = [e for e in evs if e["type"] == "gate.result"]
    assert [g["accepted"] for g in gates] == [True, False, True]
    assert any(e["type"] == "warden.manifest" and e["verdict"] == "dangerous" for e in evs)
    assert sum(e["type"] == "warden.block" for e in evs) == 1
    demo = [e for e in evs if e["type"] == "task.end" and e["taskId"] == "ledgerly-07"]
    assert [d["pass"] for d in demo] == [False, False, False, True]
    # held-out content never reaches the teacher: teacher calls carry no task id
    assert all(e["taskId"] is None for e in evs if e["type"] == "model.call" and e["role"] == "teacher")
