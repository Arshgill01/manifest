"""Baseline mode (SPEC 4.1): a plain tool-calling loop. The student decides everything.

The pieces here (TOOL_SCHEMAS, dispatch, student_turn) are also what the seed `ask-student` routine uses,
so controller mode with only seed routines behaves like the baseline.
"""

from __future__ import annotations

import time
from typing import Any

from harness.student import TaskStop
from harness.tools import ToolError, Tools, WardenBlock

SYSTEM_PROMPT = (
    "You are a coding agent working inside a small Python repository. Use the tools to inspect files, "
    "run the tests and edit files to complete the task. Paths are relative to the repository root. "
    "When you are finished, reply with a short summary and do not call any tool."
)

TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "list_files", "description": "List all files in the repository.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a file, optionally only lines start..end (1-indexed, inclusive). "
                                            "Output lines are prefixed with their line numbers.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "file path relative to the repository root"},
            "start": {"type": "integer", "description": "first line to read (optional)"},
            "end": {"type": "integer", "description": "last line to read (optional)"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "run_tests", "description": "Run the pytest suite (or only `selector`, e.g. a test file or node id).",
        "parameters": {"type": "object", "properties": {
            "selector": {"type": "string", "description": "optional pytest path / node id / -k expression"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "edit_file", "description": "Replace one exact occurrence of `search` in a file with `replace`. "
                                            "`search` must match the file exactly (without line-number prefixes).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "search": {"type": "string"}, "replace": {"type": "string"}},
            "required": ["path", "search", "replace"]}}},
    {"type": "function", "function": {
        "name": "bash", "description": "Run a shell command in the repository root.",
        "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}},
]

RESULT_CAP = 6000          # chars of one tool result shown to the student
HISTORY_BUDGET = 36_000    # chars of conversation (~10k tokens) before old tool results are elided


def _cap(text: str, cap: int = RESULT_CAP) -> str:
    if len(text) <= cap:
        return text
    head = cap * 2 // 3
    return text[:head] + f"\n... [{len(text) - cap} chars omitted] ...\n" + text[-(cap - head):]


def _int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def dispatch(tools: Tools, name: str, args: dict) -> tuple[str, Any]:
    """Run one student tool call. Returns (text for the student, raw result or None)."""
    args = args if isinstance(args, dict) else {}
    try:
        if name == "list_files":
            r = tools.list_files()
            return "\n".join(r) or "(no files)", r
        if name == "read_file":
            start, end = _int(args.get("start")), _int(args.get("end"))
            r = tools.read_file(str(args.get("path", "")), start, end)
            first = start or 1
            numbered = "".join(f"{first + i:4d}| {line}" for i, line in enumerate(r.splitlines(keepends=True)))
            return _cap(numbered or "(empty)"), r
        if name == "run_tests":
            sel = args.get("selector") or None
            r = tools.run_tests(str(sel) if sel else None)
            return _cap(f"{r['failed']} failed, {r['passed']} passed\n\n{r['output']}"), r
        if name == "edit_file":
            r = tools.edit_file(str(args.get("path", "")), args.get("search", ""), args.get("replace", ""))
            return (f"Edited {r['path']}." if r["ok"] else f"ERROR: edit failed for {r['path']}: {r['error']}"), r
        if name == "bash":
            r = tools.bash(str(args.get("cmd", "")))
            return _cap(f"exit code {r['exitCode']}\n{r['output']}", 4000), r
        return f"ERROR: unknown tool {name!r}. Available: list_files, read_file, run_tests, edit_file, bash.", None
    except WardenBlock as e:
        return f"BLOCKED by Warden: {e}", None
    except (ToolError, OSError, TypeError, ValueError) as e:
        return f"ERROR: {e}", None


def fit(messages: list[dict], budget: int = HISTORY_BUDGET) -> list[dict]:
    """Elide the oldest tool results until the conversation fits the char budget (keeps the last 4 messages)."""
    out = [dict(m) for m in messages]
    total = sum(len(str(m.get("content", ""))) for m in out)
    for m in out[:-4]:
        if total <= budget:
            break
        if m.get("role") == "tool" and len(m.get("content", "")) > 200:
            total -= len(m["content"]) - 40
            m["content"] = "[old tool output elided to save context]"
    return out


def student_turn(messages: list[dict], tools: Tools, student: Any) -> dict:
    """One model turn + its tool calls, appended to `messages` in place.

    Returns {done, calls: [{name, arguments, raw}]}; done = the student replied without calling a tool.
    """
    reply = student.chat(fit(messages), TOOL_SCHEMAS)
    messages.append(reply["message"])
    calls = []
    for call in reply["tool_calls"]:
        text, raw = dispatch(tools, call["name"], call["arguments"])
        messages.append({"role": "tool", "tool_name": call["name"], "content": text})
        calls.append({**call, "raw": raw})
    return {"done": not reply["tool_calls"], "calls": calls, "content": reply["content"]}


def initial_messages(task: str) -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": task.strip()}]


def run_baseline(tools: Tools, student: Any, *, task: str, max_steps: int = 12,
                 deadline: float | None = None) -> dict:
    """Plain loop: model turn, run its tools, repeat until it stops calling tools or limits hit."""
    messages = initial_messages(task)
    steps, done, stop = 0, False, "max_steps"
    try:
        while steps < max_steps:
            if deadline is not None and time.monotonic() >= deadline:
                stop = "timeout"
                break
            steps += 1
            turn = student_turn(messages, tools, student)
            if turn["done"]:
                done, stop = True, "student_done"
                break
    except TaskStop as e:
        stop = type(e).__name__
    return {"steps": steps, "selfReportedDone": done, "stopReason": stop, "messages": messages}
