"""triage-fix: force the deterministic repair loop.

1. run the FULL suite (no selector) and record failures/last_full_run
2. pick the innermost non-test traceback frame of the first failure as the suspect
3. read a bounded window around that line into context_snippet
4. ask the student for exactly ONE search/replace patch against that file
5. apply it, then re-run the FULL suite and record the result

Bounded to MAX_RUNS and gives up after two unappliable patches, so `ask-student` (last in the
registry) still gets control. No network, no subprocess, no env, tests/ is never written.
"""

NAME = "triage-fix"

MAX_RUNS = 3
BACK = 20
FWD = 45


def applies(state):
    if state.done or state.notes.get("triage_giveup"):
        return False
    return state.routine_runs.get(NAME, 0) < MAX_RUNS


def _clean(path):
    return str(path or "").replace("\\", "/")


def _is_target(f):
    if not f or f.startswith("/") or not f.endswith(".py"):
        return False
    if f.startswith("tests/") or "/tests/" in f or f.endswith("conftest.py"):
        return False
    if "site-packages" in f or "dist-packages" in f or "/lib/python" in f:
        return False
    return True


def _pick_frame(frames):
    picks = [fr for fr in (frames or []) if _is_target(_clean(fr.get("file")))]
    if picks:
        return picks[-1]
    return (frames or [None])[-1]


def _full_run(state, tools):
    res = tools.run_tests()
    state.test_output = (res.get("output") or "")[:20000]
    state.failures = res.get("failures") or []
    state.last_full_run = {"passed": res.get("passed"), "failed": res.get("failed")}
    return res


def run(state, tools, student):
    ran = False
    if not state.failures or not state.last_full_run or state.last_full_run.get("failed"):
        res = _full_run(state, tools)
        ran = True
        if not res.get("failed"):
            state.done = True
            state.summary = "full suite green (%s passed)" % res.get("passed")
            return state
    if not state.failures:
        state.summary = "suite still failing but no failure records; deferring to ask-student"
        return state

    fail = state.failures[0]
    test = fail.get("test") or "?"
    err = (fail.get("error") or "").splitlines()[0][:200]
    frames = fail.get("frames") or []
    fr = _pick_frame(frames) or {}
    path = _clean(fr.get("file"))
    try:
        line = int(fr.get("line") or 1)
    except (TypeError, ValueError):
        line = 1
    if not path:
        state.summary = "no usable frame for " + str(test)
        return state

    state.suspect = {"file": path, "line": line, "function": fr.get("function")}
    start = max(1, line - BACK)
    try:
        snippet = tools.read_file(path, start=start, end=start + BACK + FWD)
    except Exception:
        snippet = ""
    state.context_snippet = snippet

    trace = "\n".join("%s:%s in %s" % (_clean(x.get("file")), x.get("line"), x.get("function"))
                      for x in frames[-6:])
    prompt = (
        "Failing test: %s\nError: %s\nTraceback (innermost last):\n%s\n\n"
        "File %s, lines %d-%d:\n%s\n\n"
        "Return ONE exact search/replace edit in this file that fixes the failure. "
        "'search' must be copied verbatim from the file above, short but unique."
    ) % (test, err, trace, path, start, start + BACK + FWD, snippet)

    try:
        patch = student.ask("patch", prompt)
    except Exception:
        patch = None

    applied = False
    if isinstance(patch, dict):
        tgt = _clean(patch.get("file") or patch.get("path") or path)
        search = patch.get("search") or patch.get("find") or ""
        replace = patch.get("replace")
        if replace is None:
            replace = patch.get("replacement")
        if replace is None:
            replace = ""
        if search and tgt and not tgt.startswith("tests/") and tgt.endswith(".py"):
            seen = set((p.get("file"), p.get("search")) for p in state.patches)
            if (tgt, search) not in seen:
                try:
                    applied = bool(tools.edit_file(tgt, search, replace).get("ok"))
                except Exception:
                    applied = False
                state.patches.append({"file": tgt, "search": search,
                                      "replace": replace, "ok": applied})

    if not applied:
        misses = int(state.notes.get("triage_misses", 0)) + 1
        state.notes["triage_misses"] = misses
        if misses >= 2:
            state.notes["triage_giveup"] = True
        if ran:
            state.summary = "%s: no appliable patch; handing back to ask-student" % test
            return state
        ran = True

    res = _full_run(state, tools)
    if not res.get("failed"):
        state.done = True
        state.summary = "fixed %s: full suite green (%s passed)" % (test, res.get("passed"))
    else:
        state.summary = "%s: patch %s; still %s failing" % (
            test, "applied" if applied else "not applied", res.get("failed"))
    return state
