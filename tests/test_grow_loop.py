import json

import pytest

from growth import stubs
from growth.grow import GROWN_DIR, SKILLS_DIR, GrowConfig, grow, with_routine
from harness.log import EventLog, read_events
from harness.teacher import FAKE_PROPOSALS, FakeTeacher

GOOD_A, DANGEROUS, GOOD_B, GOOD_C = FAKE_PROPOSALS


def cfg(tmp_path, **kw):
    kw.setdefault("round0", "heldout")
    return GrowConfig(fake_teacher=True, stub_runner=True, splits=dict(stubs.STUB_SPLITS),
                      scratch_root=tmp_path, log_path=tmp_path / "run.jsonl", **kw)


def snapshot(*dirs):
    return {d: sorted(p.relative_to(d).as_posix() for p in d.rglob("*")) if d.exists() else None for d in dirs}


def test_full_dry_run(tmp_path):
    before = snapshot(GROWN_DIR, SKILLS_DIR)
    s = grow(cfg(tmp_path))
    assert snapshot(GROWN_DIR, SKILLS_DIR) == before, "dry run must never touch routines/grown or skills/"

    assert s["routinesAccepted"] == ["run-full-suite-first", "trace-to-source", "verify-and-rollback"]
    assert s["roundsRun"] == 4 and len(s["heldoutByRound"]) == 5 and len(s["avgModelCallsByRound"]) == 5

    reg = json.loads(open(s["paths"]["registry"]).read())
    names = [e["name"] for e in reg]
    assert names[0] == "start" and names[-1] == "ask-student"
    assert names[1:-1] == s["routinesAccepted"]

    for name in s["routinesAccepted"]:
        skill = tmp_path.joinpath(s["paths"]["skills"], name)
        md = (skill / "SKILL.md").read_text()
        assert md.startswith(f"---\nname: {name}\ndescription: ")
        assert (skill / "scripts" / "routine.py").exists() and (skill / "manifest.json").exists()
        grown = tmp_path.joinpath(s["paths"]["grown"], name)
        assert {p.name for p in grown.iterdir()} == {"routine.py", "SKILL.md", "manifest.json", "proposal.json"}

    events = read_events(tmp_path / "run.jsonl")
    types = [e["type"] for e in events]
    assert types[0] == "run.start" and types[-1] == "run.end"
    assert types.count("growth.proposal") == types.count("warden.manifest") == types.count("gate.result") == 4
    end = events[-1]["summary"]
    assert set(end) >= {"heldoutByRound", "avgModelCallsByRound", "teacherCostUsd", "routinesAccepted"}
    rejected = [e for e in events if e["type"] == "gate.result" and not e["accepted"]]
    assert [e["routine"] for e in rejected] == ["fetch-hints"]
    # proposal is logged before Warden, Warden before gate, per round
    for r in range(1, 5):
        seq = [e["type"] for e in events if e["round"] == r and e["type"] in ("growth.proposal", "warden.manifest", "gate.result", "eval.heldout")]
        assert seq == ["growth.proposal", "warden.manifest", "gate.result", "eval.heldout"]


def test_stops_after_two_consecutive_rejections(tmp_path):
    log = EventLog()
    teacher = FakeTeacher(log, proposals=[DANGEROUS, DANGEROUS, GOOD_A])
    s = grow(cfg(tmp_path), teacher=teacher)
    assert s["roundsRun"] == 2 and s["routinesAccepted"] == [] and "2 consecutive" in s["stopReason"]


def test_rejection_resets_after_accept(tmp_path):
    teacher = FakeTeacher(EventLog(), proposals=[DANGEROUS, GOOD_A, DANGEROUS, GOOD_B])
    s = grow(cfg(tmp_path), teacher=teacher)
    assert s["roundsRun"] == 4 and s["routinesAccepted"] == ["run-full-suite-first", "trace-to-source"]


def test_edit_replaces_in_place(tmp_path):
    edited = dict(GOOD_B, routine_py=GOOD_B["routine_py"] + "\n# v2: tighter window\n", rationale="tighten")
    teacher = FakeTeacher(EventLog(), proposals=[GOOD_B, edited])
    # whatever the gate decides, the registry must never hold two entries with one name
    s = grow(cfg(tmp_path, rounds=2), teacher=teacher)
    assert s["registry"].count("trace-to-source") <= 1


def test_with_routine_ordering():
    seed = [{"name": "start", "path": "a", "source": "seed"}, {"name": "ask-student", "path": "b", "source": "seed"}]
    r = with_routine(seed, {"name": "x", "path": "x", "source": "grown"})
    r = with_routine(r, {"name": "y", "path": "y", "source": "grown"})
    assert [e["name"] for e in r] == ["start", "x", "y", "ask-student"]
    r = with_routine(r, {"name": "x", "path": "x2", "source": "grown"})
    assert [e["path"] for e in r] == ["a", "x2", "y", "b"]
    with pytest.raises(ValueError):
        with_routine(r, {"name": "start", "path": "z", "source": "grown"})


def test_fake_teacher_refused_outside_scratch(tmp_path):
    with pytest.raises(RuntimeError, match="never write"):
        grow(GrowConfig(splits=dict(stubs.STUB_SPLITS), log_path=tmp_path / "x.jsonl"),
             teacher=FakeTeacher(EventLog()), run_split=stubs.run_split, warden=(stubs.warden_scan, stubs.warden_build))


def test_teacher_outage_still_ends_run(tmp_path):
    from harness.teacher import TeacherError

    class Down(FakeTeacher):
        def propose(self, context):
            raise TeacherError("connection refused")

    s = grow(cfg(tmp_path), teacher=Down(EventLog()))
    assert "teacher unavailable" in s["stopReason"]
    assert read_events(tmp_path / "run.jsonl")[-1]["type"] == "run.end"
