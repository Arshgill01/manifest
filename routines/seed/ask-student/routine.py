"""Seed routine (hand-written, minimal): the fallback. Show the student the task + state and let it
pick tools for one turn, i.e. baseline behaviour. Always last in the registry."""

import json

from harness.loop import initial_messages, student_turn

NAME = "ask-student"


def applies(state) -> bool:
    return not state.done


def _digest(state) -> str:
    """What other routines have learned, in the student's words. Empty when there is nothing new."""
    parts = []
    if state.last_full_run:
        parts.append(f"Last full test run: {state.last_full_run.get('failed')} failed, "
                     f"{state.last_full_run.get('passed')} passed.")
    for f in state.failures[:6]:
        where = " -> ".join(f"{fr['file']}:{fr['line']} in {fr['function']}" for fr in f.get("frames", [])[-3:])
        err = (f.get("error") or "").splitlines()[0][:200] if f.get("error") else ""
        parts.append(f"FAILED {f.get('test')}: {err}" + (f"\n  traceback: {where}" if where else ""))
    if state.suspect:
        parts.append(f"Suspected location: {json.dumps(state.suspect)}")
    if state.context_snippet:
        parts.append(f"Relevant code:\n{state.context_snippet}")
    if state.patches:
        parts.append(f"Patches applied so far: {len(state.patches)}")
    return "\n".join(parts)


def run(state, tools, student):
    if not state.messages:
        files = "\n".join(state.files)
        state.messages = initial_messages(f"{state.task.strip()}\n\nRepository files:\n{files}")
        state.notes["ask_student_seen"] = ""
    digest = _digest(state)
    if digest and digest != state.notes.get("ask_student_seen"):
        state.messages.append({"role": "user", "content": f"Harness update:\n{digest}"})

    turn = student_turn(state.messages, tools, student)

    used = []
    for call in turn["calls"]:
        used.append(call["name"])
        raw = call["raw"]
        if raw is None:
            continue
        if call["name"] == "run_tests":
            state.test_output = raw["output"]
            state.failures = raw["failures"]
            if not (call["arguments"] or {}).get("selector"):
                state.last_full_run = {"passed": raw["passed"], "failed": raw["failed"]}
        elif call["name"] == "edit_file" and raw.get("ok"):
            a = call["arguments"]
            state.patches.append({"file": raw["path"], "search": a.get("search", ""),
                                  "replace": a.get("replace", ""), "ok": True})
    state.notes["ask_student_seen"] = _digest(state)
    if turn["done"]:
        state.done = True
        state.summary = "student finished: " + (turn["content"] or "").strip().replace("\n", " ")[:120]
    else:
        state.summary = "student called " + (", ".join(used) or "nothing")
    return state
