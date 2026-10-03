"""Track A: failure labeller (process / knowledge / format) on synthetic traces."""

from growth.eval import load_index
from tasks.labels import label_task

INDEX = load_index()
TID = next(t for t, m in INDEX.items() if m["mutationKey"] == "alloc-guard")   # bug in money.allocate
META = INDEX[TID]
ROOT = META["rootCause"]["file"]
BUG_LINE = "    if total_weight >= 0:\n"


def tool(name, ok=True, summary="", **args):
    return {"type": "tool.call", "tool": name, "args": args, "ok": ok, "summary": summary}


def model(done="stop"):
    return {"type": "model.call", "role": "student", "doneReason": done}


def end(stop="max_steps"):
    return {"type": "task.end", "pass": False, "stopReason": stop}


def test_wrong_file_and_no_rerun_is_process():
    events = [model(), tool("run_tests"), model(), tool("read_file", path="src/ledgerly/invoice.py"),
              model(), tool("edit_file", path="src/ledgerly/invoice.py", search="x", replace="y"), end()]
    r = label_task(TID, events, META)
    assert r["label"] == "process"
    assert any("wrong file" in x for x in r["reasons"])
    assert any("never re-ran" in x for x in r["reasons"])


def test_right_function_rerun_but_wrong_fix_is_knowledge():
    events = [model(), tool("run_tests"), model(), tool("read_file", path=ROOT),
              model(), tool("edit_file", path=ROOT, search=BUG_LINE, replace="    if total_weight > 1:\n"),
              model(), tool("run_tests"), end("student_done")]
    r = label_task(TID, events, META)
    assert r["label"] == "knowledge" and r["editedRootFunction"] and r["fullRerunAfterEdit"]


def test_mostly_broken_tool_calls_is_format():
    events = [model(), tool("edit_file", ok=False, summary="ERROR: search text not found", path=ROOT, search="zz"),
              model(), tool("frobnicate", ok=False, summary="ERROR: unknown tool 'frobnicate'"),
              model(), tool("run_tests"), end()]
    assert label_task(TID, events, META)["label"] == "format"


def test_looping_is_process_even_in_right_file():
    loop = [model(), tool("read_file", path=ROOT)] * 3
    events = loop + [model(), tool("edit_file", path=ROOT, search=BUG_LINE, replace="    if total_weight > 1:\n"),
                     model(), tool("run_tests"), end()]
    r = label_task(TID, events, META)
    assert r["label"] == "process" and any("repeated" in x for x in r["reasons"])
