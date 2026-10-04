"""growth/stats.py: bootstrap, paired CI, McNemar; growth/results.py renders from logs."""

import json

import pytest

from growth.stats import bootstrap_ci, discordant, mcnemar_exact, paired_ci, success_ci


def test_bootstrap_brackets_the_point_and_is_deterministic():
    p, lo, hi = success_ci([True] * 3 + [False] * 5)
    assert p == pytest.approx(0.375) and lo <= p <= hi and 0 <= lo and hi <= 1
    assert bootstrap_ci([1, 2, 3, 4]) == bootstrap_ci([1, 2, 3, 4])
    assert success_ci([True] * 4) == (1.0, 1.0, 1.0)


def test_mcnemar_exact_values():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(0, 6) == pytest.approx(2 / 64)      # 2 * (1/2)^6
    assert mcnemar_exact(3, 3) == 1.0


def test_paired_and_discordant():
    a = {"t1": 1.0, "t2": 0.0, "t3": 0.0}
    b = {"t1": 1.0, "t2": 1.0, "t3": 1.0, "t4": 1.0}
    d, lo, hi, n = paired_ci(a, b)
    assert n == 3 and d == pytest.approx(2 / 3) and lo <= d <= hi
    assert discordant({k: bool(v) for k, v in a.items()}, {k: bool(v) for k, v in b.items()}) == (1, 0, 2, 0)


def test_results_render_from_a_log(tmp_path, monkeypatch):
    import growth.results as gr
    from harness.log import EventLog
    log = EventLog(tmp_path / "r.jsonl")
    log.emit("run.start", mode="baseline", student="s", teacher=None, online=False, maxSteps=12, maxSeconds=1800)
    for tid, ok in (("ledgerly-01", True), ("csvflow-01", False)):
        with log.scope(round=0, taskId=tid, split="heldout"):
            log.emit("task.start", domain=tid.split("-")[0], bugShape="x")
            log.emit("model.call", model="s", role="student", purpose="chat", promptTokens=100, outTokens=10, ms=5)
            log.emit("task.end", **{"pass": ok}, steps=3, modelCalls=1, routineCalls=0, ms=1000, stopReason="max_steps")
    monkeypatch.setattr(gr, "ROOT", tmp_path)
    monkeypatch.setattr(gr, "_index", lambda: {})
    monkeypatch.setattr(gr, "_splits", lambda: {"profiles": {"full": {"heldout": ["ledgerly-01", "csvflow-01"], "gate": [], "train": []}}})
    cfg = {"reference": "E1", "experiments": [{"id": "E1", "label": "base", "log": "r.jsonl"}]}
    text = gr.render(cfg, tmp_path / "experiments.json")
    assert "| E1 base | 1/2 |" in text and "`csvflow-01`" in text
