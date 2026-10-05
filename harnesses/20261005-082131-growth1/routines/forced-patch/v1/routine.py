"""Force a focused patch when the student keeps reading files without editing anything.

After a few read-only student turns with a failing suite the long conversation makes the model
narrate a diagnosis instead of acting. This routine interrupts with one short question - the
failing test, its error and the code at the deepest non-test traceback frame - applies the
returned search/replace block and re-runs the suite, reverting a patch that makes it worse.
"""

NAME = "forced-patch"

MAX_TRIES = 2
FIRST_AFTER = 4
GAP = 3
PAD = 20


def applies(state) -> bool:
    if state.done or not state.failures:
        return False
    tries = state.notes.get("forced_patch_tries", 0)
    if tries >= MAX_TRIES:
        return False
    ask_runs = state.routine_runs.get("ask-student", 0)
    if tries == 0:
        # only the pathology seen in practice: many reads, no edit at all
        return ask_runs >= FIRST_AFTER and not state.patches
    return ask_runs - state.notes.get("forced_patch_at", 0) >= GAP


def _source_frame(failure) -> dict:
    frames = failure.get("frames") or []
    for frame in reversed(frames):
        path = (frame.get("file") or "").replace("\\", "/")
        if path and not path.startswith("tests/") and not path.startswith("test_"):
            return frame
    return {}


def _pick_failure(state) -> dict:
    for failure in state.failures:
        if _source_frame(failure):
            return failure
    return state.failures[0]


def _excerpt(tools, path, line) -> str:
    if not path:
        return ""
    try:
        lines = tools.read_file(path).splitlines()
    except Exception:
        return ""
    if not lines:
        return ""
    center = max(1, int(line or 1))
    lo = max(0, center - 1 - PAD)
    hi = min(len(lines), center + PAD)
    return "\n".join(f"{i + 1}: {lines[i]}" for i in range(lo, hi))


def _prompt(state, failure, path, snippet) -> str:
    err = "\n".join((failure.get("error") or "").strip().splitlines()[:4])[:600]
    others = [f.get("test") for f in state.failures if f.get("test") != failure.get("test")]
    tail = "Other failing tests: " + ", ".join(others[:6]) if others else ""
    return (
        "A test in this repository fails. Apply the smallest source fix.\n"
        f"Failing test: {failure.get('test')}\n"
        f"Error:\n{err}\n{tail}\n\n"
        f"Code from {path}:\n{snippet}\n\n"
        "Answer with the file to change and one exact search/replace block copied from it. "
        "Never edit tests/."
    )


def _record(state, result) -> None:
    state.test_output = result.get("output", state.test_output)
    state.failures = result.get("failures", state.failures)
    if result.get("failed") == 0:
        state.last_full_run = {"passed": result.get("passed", 0), "failed": 0}
        state.done = True


def run(state, tools, student):
    state.notes["forced_patch_tries"] = state.notes.get("forced_patch_tries", 0) + 1
    state.notes["forced_patch_at"] = state.routine_runs.get("ask-student", 0)

    before = tools.run_tests()
    _record(state, before)
    if state.done:
        state.summary = "suite already passes; nothing forced"
        return state
    before_failed = int(before.get("failed") or 0)

    failure = _pick_failure(state)
    frame = _source_frame(failure)
    path = frame.get("file") or ""
    snippet = _excerpt(tools, path, frame.get("line"))

    try:
        answer = student.ask("patch", _prompt(state, failure, path, snippet)) or {}
    except Exception as exc:
        state.summary = f"forced patch: student error {exc}"
        return state

    target = answer.get("file") or path
    search = answer.get("search") or ""
    replace = answer.get("replace") or ""
    if not target or not search:
        state.summary = "forced patch: no usable patch returned"
        return state

    try:
        applied = tools.edit_file(target, search, replace)
    except Exception as exc:
        state.summary = f"forced patch: edit rejected ({exc})"
        return state
    if not applied.get("ok"):
        state.summary = f"forced patch: could not apply on {target}"
        return state

    state.patches.append({"file": target, "search": search, "replace": replace, "ok": True})
    after = tools.run_tests()
    _record(state, after)
    if not state.done and int(after.get("failed") or 0) > before_failed:
        try:
            undone = tools.edit_file(target, replace, search)
        except Exception:
            undone = {"ok": False}
        if undone.get("ok"):
            state.patches[-1]["ok"] = False
            state.patches[-1]["reverted"] = True
            _record(state, tools.run_tests())
            state.summary = f"forced patch on {target} reverted (suite got worse)"
            return state
    state.summary = (f"forced patch on {target}: {after.get('passed')} passed, "
                     f"{after.get('failed')} failed")
    return state
