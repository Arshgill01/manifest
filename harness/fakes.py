"""Scripted stand-in for `Student` (tests, dry runs). Same surface: .chat, .ask, .calls, .deadline, .max_calls.

    s = ScriptedStudent(chat=[{"tool": "run_tests"}, {"tool": "edit_file", "args": {...}}, "done"],
                        ask={"diagnose": [{"file": ..., "function": ..., "hypothesis": ...}]})

A chat script item is "done"/str (final text, no tool call), {"tool", "args"} or {"calls": [{tool, args}, ...]}.
When the chat script runs out the student says it is done. Asks pop per purpose (falls back to key "*").
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel

from harness.log import EventLog
from harness.student import FORMATS, BudgetExceeded, DeadlineExceeded, StudentFormatError


class ScriptedStudent:
    role = "student"

    def __init__(self, chat: list | None = None, ask: dict[str, list] | None = None, *,
                 log: EventLog | None = None, model: str = "scripted"):
        self.chat_script = list(chat or [])
        self.ask_script = {k: list(v) for k, v in (ask or {}).items()}
        self.log = log
        self.model = model
        self.calls = 0
        self.deadline: float | None = None
        self.max_calls: int | None = None
        self.seen: list[dict] = []  # every request: {kind, purpose, messages|prompt}

    def _tick(self, purpose: str) -> None:
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise DeadlineExceeded("wall-clock limit reached before student call")
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise BudgetExceeded(f"student call budget ({self.max_calls}) exhausted")
        self.calls += 1
        if self.log:
            self.log.emit("model.call", model=self.model, role="student", purpose=purpose,
                          promptTokens=0, outTokens=0, ms=0)

    def chat(self, messages: list[dict], tools: list[dict] | None = None, *, purpose: str = "chat") -> dict:
        self._tick(purpose)
        self.seen.append({"kind": "chat", "purpose": purpose, "messages": [dict(m) for m in messages]})
        item = self.chat_script.pop(0) if self.chat_script else "done"
        if isinstance(item, str):
            return {"content": item, "tool_calls": [], "message": {"role": "assistant", "content": item}}
        raw = item.get("calls") or [item]
        calls = [{"name": c["tool"], "arguments": dict(c.get("args") or {})} for c in raw]
        message = {"role": "assistant", "content": item.get("content", ""),
                   "tool_calls": [{"function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]}
        return {"content": item.get("content", ""), "tool_calls": calls, "message": message}

    def ask(self, purpose: str, prompt: str, schema: type[BaseModel] | None = None) -> dict:
        self._tick(purpose)
        self.seen.append({"kind": "ask", "purpose": purpose, "prompt": prompt})
        queue = self.ask_script.get(purpose) or self.ask_script.get("*") or []
        if not queue:
            raise StudentFormatError(f"{purpose}: scripted student has no answer")
        answer = queue.pop(0)
        schema = schema or FORMATS.get(purpose)
        return schema.model_validate(answer).model_dump() if schema else dict(answer)
