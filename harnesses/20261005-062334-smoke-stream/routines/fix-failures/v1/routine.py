"""Deterministic repair loop for a failing pytest suite: refresh the full-suite result, then ask
one focused question about the innermost project frame of the next unrepaired failure, apply that
single edit, re-run the whole suite, and revert the edit if the suite got strictly worse."""
import re
from pydantic import BaseModel
NAME = "fix-failures"
MAX_TRIES = 2

class PatchOut(BaseModel):
    file: str = ""
    search: str = ""
    replace: str = ""

def _norm(path) -> str:
    return re.sub(r"^\./+", "", str(path or "").replace("\\", "/"))

def _is_test(path) -> bool:
    parts = _norm(path).split("/")
    base = parts[-1]
    return ("tests" in parts or "testing" in parts or base.startswith(("test_", "conftest"))
            or base.endswith("_test.py"))

def _stale(state) -> bool:
    return (state.last_full_run is None
            or len(state.patches) != int(state.notes.get("verified_count", 0)))

def _refresh(state, tools) -> None:
    previous = (state.last_full_run or {}).get("failed")
    result = tools.run_tests()
    state.test_output = result.get("output", "")
    state.failures = result.get("failures") or []
    failed, passed = int(result.get("failed", 0)), int(result.get("passed", 0))
    state.last_full_run = {"passed": passed, "failed": failed}
    state.notes["verified_count"] = len(state.patches)
    note = ""
    if failed and previous is not None and failed > int(previous) and state.patches:
        last = state.patches[-1]
        if tools.edit_file(last["file"], last["replace"], last["search"]).get("ok"):
            state.patches.pop()
            state.notes["verified_count"] = -1
            state.notes["just_reverted"] = True
            note = f"; reverted harmful edit in {last['file']}"
    if failed == 0:
        state.done = True
    state.summary = f"{failed} failed, {passed} passed{note}"

def _candidates(state):
    """Non-test traceback frames of each failure, innermost frames first, untried ones only."""
    attempts = state.notes.get("attempts") or {}
    ranked = []
    for index, failure in enumerate(state.failures):
        depth = 0
        for frame in reversed(failure.get("frames") or []):
            path = _norm(frame.get("file"))
            if path.endswith(".py") and not _is_test(path):
                depth += 1
                ranked.append((depth, index, path, frame, failure))
    ranked.sort(key=lambda item: (item[0], item[1]))
    out, seen = [], set()
    for depth, index, path, frame, failure in ranked:
        key = f"{path}:{frame.get('line')}"
        if key in seen or attempts.get(key, 0) >= MAX_TRIES:
            continue
        seen.add(key)
        error = str(failure.get("error") or "").splitlines()
        out.append({"file": path, "line": int(frame.get("line") or 1), "key": key,
                    "function": str(frame.get("function") or ""),
                    "test": failure.get("test", ""), "error": error[0][:200] if error else "",
                    "frames": (failure.get("frames") or [])[-4:]})
    return out

def _snippet(source: str, line: int) -> str:
    """The enclosing def/class of `line` (or a bounded window) so one question stays short."""
    lines = source.splitlines()
    if not lines:
        return ""
    i = max(0, min(len(lines) - 1, int(line) - 1))
    start = max(0, i - 30)
    for j in range(i, start - 1, -1):
        if lines[j].lstrip().startswith(("def ", "async def ", "class ")):
            start = j
            break
    return "\n".join(lines[start:min(len(lines), i + 15)])

def applies(state) -> bool:
    return not state.done and (_stale(state) or bool(_candidates(state)))

def run(state, tools, student):
    if _stale(state):
        _refresh(state, tools)
        if state.done or state.notes.pop("just_reverted", False):
            return state
    candidates = _candidates(state)
    if not candidates:
        state.summary = state.summary or "no patchable source frame left"
        return state
    cand = candidates[0]
    attempts = state.notes.setdefault("attempts", {})
    tries = int(attempts.get(cand["key"], 0))
    attempts[cand["key"]] = tries + 1
    state.suspect = {"file": cand["file"], "line": cand["line"], "function": cand["function"]}
    try:
        state.context_snippet = _snippet(tools.read_file(cand["file"]), cand["line"])
    except Exception:
        state.context_snippet = ""
    where = " -> ".join(f"{f.get('file')}:{f.get('line')}" for f in cand["frames"])
    prompt = (
        "A pytest suite fails. Fix the bug in the project's own source code. Never edit tests.\n"
        f"Failing test: {cand['test']}\nError: {cand['error']}\n"
        f"Traceback (outermost first): {where}\n"
        f"Failing line: {cand['file']}:{cand['line']} in {cand['function']}()\n\n"
        f"Current source of {cand['file']}:\n-----8<-----\n{state.context_snippet}\n----->8-----\n\n"
        "Return ONE minimal edit: file (project source path), search (text copied verbatim from "
        "that file, including indentation) and replace (the corrected text)."
    )
    if tries:
        prompt += "\nA previous edit here failed or was rejected; give a different, more careful fix."
    try:
        out = student.ask("patch", prompt, PatchOut)
    except Exception:
        out = {}
    if not isinstance(out, dict):
        out = {}
    path = _norm(out.get("file") or cand["file"])
    if _is_test(path) or (state.files and path not in state.files):
        path = cand["file"]
    search = str(out.get("search") or out.get("old") or out.get("find") or "")
    replace = str(out.get("replace") or out.get("new") or "")
    if not search.strip() or search == replace:
        state.summary = f"no usable edit for {cand['key']}"
        return state
    result = tools.edit_file(path, search, replace)
    if not result.get("ok"):
        state.notes.setdefault("failed_edits", []).append({"file": path, "key": cand["key"]})
        state.summary = f"edit did not match {path}"
        return state
    state.patches.append({"file": path, "search": search, "replace": replace,
                          "ok": True, "key": cand["key"]})
    _refresh(state, tools)
    state.summary = f"patched {path} -> {state.summary}"
    return state
