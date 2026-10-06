NAME = "root-cause-patch"

MAX_TRIES = 2
FIRST_AFTER = 2
GAP = 3
CAP = 80


def _is_test(path):
    p = (path or "").replace("\\", "/")
    return p.startswith("tests/") or p.startswith("test_")


def _frames(failure):
    src = test = ""
    for fr in reversed(failure.get("frames") or []):
        p = (fr.get("file") or "").replace("\\", "/")
        if not p:
            continue
        if _is_test(p):
            test = test or p
        else:
            src = src or p
    return src, test


def _safe_read(tools, path):
    try:
        return tools.read_file(path)
    except Exception:
        return ""


def _modules(text):
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("from ") and " import " in line:
            out.append(line[5:].split(" import ")[0])
        elif line.startswith("import "):
            out += [p.split(" as ")[0] for p in line[7:].split(",")]
    return [m.strip().lstrip(".").strip() for m in out if m.strip().lstrip(".").strip()]


def _candidates(state, mods, extra):
    files = [(f or "").replace("\\", "/") for f in state.files if not _is_test(f)]
    out = []
    for mod in mods:
        rel = mod.replace(".", "/").strip("/")
        if not rel:
            continue
        for f in files:
            if (f in (rel + ".py", rel + "/__init__.py") or f.endswith("/" + rel + ".py")
                    or f.endswith("/" + rel + "/__init__.py")):
                if f not in out:
                    out.append(f)
    if extra and not _is_test(extra) and extra.replace("\\", "/") not in out:
        out.insert(0, extra.replace("\\", "/"))
    return out[:4]


def _locate(tools, cands, search):
    needle = (search or "").replace("\r\n", "\n")
    if not needle:
        return ""
    for path in cands:
        if needle in _safe_read(tools, path).replace("\r\n", "\n"):
            return path
    return ""


def applies(state):
    if state.done or not state.failures:
        return False
    if state.notes.get("rcp_tries", 0) >= MAX_TRIES:
        return False
    ask_runs = state.routine_runs.get("ask-student", 0)
    since = state.notes.get("rcp_at")
    return ask_runs >= FIRST_AFTER if since is None else ask_runs - since >= GAP


def run(state, tools, student):
    state.notes["rcp_tries"] = state.notes.get("rcp_tries", 0) + 1
    state.notes["rcp_at"] = state.routine_runs.get("ask-student", 0)
    before = tools.run_tests(); state.test_output = before.get("output", state.test_output); state.failures = before.get("failures", state.failures)
    if before.get("failed") == 0:
        state.last_full_run = {"passed": before.get("passed", 0), "failed": 0}; state.done = True
        state.summary = "root-cause patch: suite already passes"
        return state
    before_failed = int(before.get("failed") or 0)
    failures = state.failures[:4]
    frames = [_frames(f) for f in failures]
    src = next((s for s, _ in frames if s), "")
    tfiles = []
    for _, t in frames:
        if t and t not in tfiles:
            tfiles.append(t)
    mods = [m for tf in tfiles for m in _modules(_safe_read(tools, tf))]
    cands = _candidates(state, mods, src)
    if not cands:
        state.summary = "root-cause patch: no candidate source file found"
        return state
    bodies = ["\n".join(_safe_read(tools, p).splitlines()[:CAP]) for p in cands]
    blocks = "\n\n".join("--- " + p + " ---\n" + b for p, b in zip(cands, bodies))
    fails = "\n".join("FAILED %s: %s" % (f.get("test"), (((f.get("error") or "").strip().splitlines() or [""])[0])[:200]) for f in failures)
    prompt = "Several tests fail and they probably share one root cause. Fix the source code, never the tests.\n" + fails + "\n\nCandidate source files:\n" + blocks + "\n\nAnswer with the file to change and ONE exact search/replace block copied verbatim from that file that should fix as many of these failures as possible. Never edit tests/."
    try:
        answer = student.ask("patch", prompt) or {}
    except Exception as exc:
        state.summary = "root-cause patch: student error " + str(exc)
        return state
    search = answer.get("search") or ""
    replace = answer.get("replace") or ""
    target = _locate(tools, cands, search) or (answer.get("file") or "").strip().replace("\\", "/") or cands[0]
    if not search or target not in cands:
        state.summary = "root-cause patch: no usable patch returned"
        return state
    try:
        ok = tools.edit_file(target, search, replace).get("ok")
    except Exception:
        ok = False
    if not ok:
        state.summary = "root-cause patch: could not apply on " + target
        return state
    state.patches.append({"file": target, "search": search, "replace": replace, "ok": True})
    after = tools.run_tests(); state.test_output = after.get("output", state.test_output); state.failures = after.get("failures", state.failures); after_failed = int(after.get("failed") or 0)
    if after_failed == 0:
        state.last_full_run = {"passed": after.get("passed", 0), "failed": 0}
        state.done = True
    elif after_failed > before_failed:
        try:
            undone = tools.edit_file(target, replace, search)
        except Exception:
            undone = {"ok": False}
        if undone.get("ok"):
            state.patches[-1]["ok"] = False
            state.patches[-1]["reverted"] = True
            rerun = tools.run_tests(); state.test_output = rerun.get("output", state.test_output); state.failures = rerun.get("failures", state.failures)
            state.summary = "root-cause patch on " + target + " reverted (made suite worse)"
            return state
    state.summary = "root-cause patch on " + target + ": " + str(after.get("passed")) + " passed, " + str(after_failed) + " failed"
    return state
