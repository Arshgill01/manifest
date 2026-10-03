"""Track A: generated tasks are real, and the runner cannot be fooled."""

import json
import shutil

import pytest

from growth.eval import GENERATED, judge, load_index, protected_fingerprint
from tasks.gen import apply_edits, run_pytest
from tasks.mutations import Edit

INDEX = load_index()
TASK_IDS = sorted(INDEX)


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_pristine_task_fails_exactly_as_indexed(task_id):
    run = run_pytest(GENERATED / task_id)
    assert sorted(run.failed) == sorted(INDEX[task_id]["failingTests"])


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_reference_fix_passes(task_id, tmp_path):
    work = tmp_path / task_id
    shutil.copytree(GENERATED / task_id, work)
    apply_edits(work, tuple(Edit(**e) for e in INDEX[task_id]["fix"]))
    meta = INDEX[task_id]
    assert judge(work, GENERATED / task_id, len(meta["failingTests"]) + meta["passingTests"])["pass"]


def test_root_cause_metadata_never_ships_inside_task_dirs():
    for task_id, meta in INDEX.items():
        blob = "\n".join(p.read_text() for p in (GENERATED / task_id).rglob("*") if p.is_file() and p.suffix in {".md", ".py", ".ini", ".json"})
        assert meta["mutationKey"] not in blob
        assert not (GENERATED / task_id / "index.json").exists()


def _fixed_copy(tmp_path, task_id="ledgerly-01"):
    work = tmp_path / "work"
    shutil.copytree(GENERATED / task_id, work)
    return work, INDEX[task_id]


def _total(meta):
    return len(meta["failingTests"]) + meta["passingTests"]


def test_editing_a_test_is_a_fail_even_if_green(tmp_path):
    work, meta = _fixed_copy(tmp_path)
    for t in meta["failingTests"]:
        path = work / t.split("::")[0]
        name = t.split("::")[1]
        path.write_text(path.read_text().replace(f"def {name}(", f"def {name}(*_):\n    return\n\ndef _orig_{name}("))
    verdict = judge(work, GENERATED / "ledgerly-01", _total(meta))
    assert not verdict["pass"] and not verdict["testsUntouched"]


def test_adding_a_conftest_in_src_is_a_fail(tmp_path):
    work, meta = _fixed_copy(tmp_path)
    apply_edits(work, tuple(Edit(**e) for e in meta["fix"]))
    (work / "src" / "conftest.py").write_text("")
    assert not judge(work, GENERATED / "ledgerly-01", _total(meta))["pass"]


def test_deleting_tests_is_a_fail(tmp_path):
    work, meta = _fixed_copy(tmp_path)
    for f in {t.split("::")[0] for t in meta["failingTests"]}:
        (work / f).unlink()
    assert not judge(work, GENERATED / "ledgerly-01", _total(meta))["pass"]


def test_fingerprint_ignores_source_edits(tmp_path):
    work, meta = _fixed_copy(tmp_path)
    before = protected_fingerprint(work)
    apply_edits(work, tuple(Edit(**e) for e in meta["fix"]))
    assert protected_fingerprint(work) == before


def test_splits_are_disjoint_and_known():
    splits = json.loads((GENERATED.parent / "splits.json").read_text())
    for profile in splits["profiles"].values():
        seen = [t for ids in profile.values() for t in ids]
        assert len(seen) == len(set(seen))
        assert set(seen) <= set(INDEX)


def test_round0_cache_hits_with_explicit_ids(tmp_path, monkeypatch):
    import growth.eval as ev
    from harness.log import EventLog

    monkeypatch.setattr(ev, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(ev, "WORK", tmp_path / "work")
    calls = []
    real = ev.run_one
    monkeypatch.setattr(ev, "run_one", lambda *a, **k: calls.append(a) or real(*a, **k))
    ids = sorted(INDEX)[:2]
    # baseline needs track B; "noop" semantics are enough here, so pretend via mode check bypass
    monkeypatch.setattr(ev, "HARNESS_MODES", ())
    monkeypatch.setattr(ev, "SELFTEST_MODES", ("noop", "baseline"))
    first = ev.run_split("train", mode="baseline", round=0, log=EventLog(), task_ids=ids)
    log2 = EventLog()
    second = ev.run_split("train", mode="baseline", round=0, log=log2, task_ids=ids)
    assert len(calls) == 2 and first["passed"] == second["passed"] == 0
    assert log2.events and all(e.get("cached") for e in log2.events)
