NAME = "localize-patch"

MAX_TRIES, FIRST_AFTER, CAP = 3, 3, 70


def _is_test(path):
    p = (path or "").replace("\\", "/")
    return p.startswith("tests/") or p.startswith("test_")


def _blind(state):
    out = []
    for f in state.failures:
        if not [fr for fr in (f.get("frames") or []) if not _is_test(fr.get("file"))]:
            out.append(f)
    return out


def applies(state):
    if state.done or not state.failures:
        return False
    if state.notes.get("lp_tries", 0) >= MAX_TRIES:
        return False
    if not _blind(state):
        return False
    return state.routine_runs.get("ask-student", 0) >= FIRST_AFTER


def _test_file(failure):
    frames = failure.get("frames") or []
    for fr in list(reversed(frames)) + frames:
        if _is_test(fr.get("file")):
            return (fr.get("file") or "").replace("\\", "/")
    return ""


def _modules(text):
    raw_lines = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("from ") and " import " in line:
            raw_lines.append(line[5:].split(" import ")[0])
        elif line.startswith("import "):
            for part in line[7:].split(","):
                raw_lines.append(part.split(" as ")[0])
    mods = []
    for m in raw_lines:
        m = m.strip().lstrip(".").strip()
        if m:
            mods.append(m)
    return mods


def _candidates(state, mods):
    files = [f.replace("\\", "/") for f in state.files]
    out = []
    for mod in mods:
        rel = mod.replace(".", "/").strip("/")
        if not rel:
            continue
        for f in files:
            hit = (f == rel + ".py" or f.endswith("/" + rel + ".py")
                   or f == rel + "/__init__.py" or f.endswith("/" + rel + "/__init__.py"))
            if hit and f not in out:
                out.append(f)
    return out[:4]


def _prompt(failure, test_body, cands, bodies):
    err = "\n".join((failure.get("error") or "").strip().splitlines()[:5])[:500]
    blocks = "\n\n".join(f"--- {p} ---\n{b}" for p, b in zip(cands, bodies))
    return (
        "A test fails and its traceback points only at the test file, so the bug is inside a source\n"
        "module that the test imports.\n"
        f"Failing test: {failure.get('test')}\nError:\n{err}\n\n"
        f"Test file:\n{test_body}\n\nCandidate source files:\n{blocks}\n\n"
        "Answer with the file to change (choose one of the candidates) and one exact search/replace\n"
        "block copied verbatim from that file. Never edit tests/."
    )


def _locate(tools, cands, search):
    needle = (search or "").replace("\r\n", "\n")
    if not needle:
        return ""
    for path in cands:
        try:
            text = tools.read_file(path).replace("\r\n", "\n")
        except Exception:
            continue
        if needle in text:
            return path
    return ""


def run(state, tools, student):
    state.notes["lp_tries"] = state.notes.get("lp_tries", 0) + 1
    attempt = state.notes["lp_tries"] - 1

    before = tools.run_tests()
    state.test_output = before.get("output", state.test_output)
    state.failures = before.get("failures", state.failures)
    if before.get("failed") == 0:
        state.last_full_run = {"passed": before.get("passed", 0), "failed": 0}
        state.done = True
        state.summary = "suite passes; nothing to localise"
        return state
    before_failed = int(before.get("failed") or 0)

    pool = _blind(state) or state.failures
    failure = pool[attempt % len(pool)]
    tfile = _test_file(failure)
    try:
        ttext = tools.read_file(tfile) if tfile else ""
    except Exception:
        ttext = ""
    cands = _candidates(state, _modules(ttext))
    if not cands:
        state.summary = "localize patch: no candidate source file found"
        return state

    bodies = []
    for path in cands:
        try:
            bodies.append("\n".join(tools.read_file(path).splitlines()[:CAP]))
        except Exception:
            bodies.append("")

    try:
        answer = student.ask("patch", _prompt(failure, "\n".join(ttext.splitlines()[:CAP]), cands, bodies)) or {}
    except Exception as exc:
        state.summary = f"localize patch: student error {exc}"
        return state

    search = answer.get("search") or ""
    replace = answer.get("replace") or ""
    target = (answer.get("file") or "").strip().replace("\\", "/") or cands[0]
    located = _locate(tools, cands, search)
    if located:
        target = located
    elif target not in cands:
        state.summary = "localize patch: answer names no candidate file"
        return state
    if not search:
        state.summary = "localize patch: no patch returned"
        return state

    try:
        applied = tools.edit_file(target, search, replace)
    except Exception as exc:
        state.summary = f"localize patch: edit rejected ({exc})"
        return state
    if not applied.get("ok"):
        state.summary = f"localize patch: could not apply on {target}"
        return state

    state.patches.append({"file": target, "search": search, "replace": replace, "ok": True})
    after = tools.run_tests()
    state.test_output = after.get("output", state.test_output)
    state.failures = after.get("failures", state.failures)
    if after.get("failed") == 0:
        state.last_full_run = {"passed": after.get("passed", 0), "failed": 0}
        state.done = True
    elif int(after.get("failed") or 0) > before_failed:
        try:
            undone = tools.edit_file(target, replace, search)
        except Exception:
            undone = {"ok": False}
        if undone.get("ok"):
            state.patches[-1]["ok"] = False
            state.patches[-1]["reverted"] = True
            state.test_output = tools.run_tests().get("output", state.test_output)
            state.summary = f"localize patch on {target} reverted (suite got worse)"
            return state
    state.summary = f"localize patch on {target}: {after.get('passed')} passed, {after.get('failed')} failed"
    return state
