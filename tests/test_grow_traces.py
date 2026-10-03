from growth.traces import compress_failed_traces, compress_task


def ev(type, task="t1", split="train", **kw):
    return {"ts": "x", "type": type, "round": 1, "taskId": task, "split": split, **kw}


def test_compress_task_keeps_function_level_and_collapses_repeats():
    events = [
        ev("task.start", domain="d", bugShape="deep-call-chain"),
        ev("routine.call", routine="start", summary="listed", ms=3),
        *[ev("tool.call", tool="read_file", args={"path": "tests/test_a.py"}, ok=True, summary="x")] * 4,
        ev("model.call", model="qwen", role="student", purpose="diagnose", promptTokens=10, outTokens=5, ms=9),
        ev("model.call", model="ds", role="teacher", purpose="propose", promptTokens=1, outTokens=1, ms=1),
        ev("task.end", **{"pass": False}, steps=12, modelCalls=9, routineCalls=3, ms=100),
    ]
    c = compress_task("t1", events)
    assert c["domain"] == "d" and c["bugShape"] == "deep-call-chain"
    assert c["outcome"] == {"pass": False, "steps": 12, "modelCalls": 9, "routineCalls": 3, "ms": 100}
    assert c["trace"][0] == {"routine": "start", "summary": "listed"}
    assert c["trace"][1]["tool"] == "read_file" and c["trace"][1]["repeat"] == 4
    assert c["trace"][2] == {"student": "diagnose", "promptTokens": 10, "outTokens": 5}
    assert len(c["trace"]) == 3  # teacher call dropped


def test_drops_other_splits_and_tasks_and_bounds_length():
    events = [ev("tool.call", tool=f"t{i}", args={}, ok=True, summary="s") for i in range(60)]
    events += [ev("tool.call", split="heldout", tool="LEAK", args={}, ok=True, summary="s")]
    events += [ev("tool.call", task="other", tool="LEAK", args={}, ok=True, summary="s")]
    c = compress_task("t1", events)
    assert "LEAK" not in str(c)
    assert len(c["trace"]) == 29 and c["trace"][14] == {"omitted": 32}


def test_long_strings_clipped():
    c = compress_task("t1", [ev("tool.call", tool="run_tests", args={}, ok=False, summary="E" * 5000)])
    assert len(c["trace"][0]["summary"]) < 800


def test_failed_only_train_only_max_six_diverse():
    results = []
    for i in range(10):
        results.append({"taskId": f"a-{i:02d}", "pass": False, "events": [ev("task.start", task=f"a-{i:02d}", domain="a", bugShape="s1" if i < 8 else "s2")]})
    results.append({"taskId": "ok-01", "pass": True, "events": []})
    results.append({"taskId": "held-01", "pass": False, "events": []})
    train_ids = [r["taskId"] for r in results if r["taskId"] != "held-01"]
    picked = compress_failed_traces({"results": results}, train_ids=train_ids, max_traces=6)
    ids = [p["taskId"] for p in picked]
    assert len(ids) == 6 and "ok-01" not in ids and "held-01" not in ids
    assert {"a-08", "a-09"} & set(ids)  # the rarer bug shape is represented


def test_cycles_collapse_ignoring_token_counts():
    cycle = lambda i: [
        ev("routine.call", routine="ask-student", summary="pick", ms=1),
        ev("model.call", role="student", purpose="ask", promptTokens=100 + i, outTokens=5, ms=1),
        ev("tool.call", tool="read_file", args={"path": "a.py"}, ok=True, summary="read"),
    ]
    events = [e for i in range(5) for e in cycle(i)] + [ev("tool.call", tool="run_tests", args={}, ok=False, summary="1 failed")]
    trace = compress_task("t1", events)["trace"]
    assert len(trace) == 5
    assert trace[3] == {"loop": "previous 3 steps repeated", "times": 5}
    assert trace[4]["tool"] == "run_tests"
