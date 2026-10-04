"""Student model client: qwen3.5:4b on local Ollama (SPEC 1, CONTRACT 2.3).

    student = Student(log)
    reply = student.chat(messages, TOOL_SCHEMAS)        # baseline turn -> {content, tool_calls, message}
    d = student.ask("diagnose", prompt)                  # fixed format -> {file, function, hypothesis}
    p = student.ask("patch", prompt)                     # fixed format -> {file, search, replace}
    x = student.ask("anything", prompt, MyModel)         # any pydantic schema; invalid output re-asked once

Every call logs `model.call` (role "student"). `deadline`/`max_calls` raise `TaskStop` subclasses, which
derive from BaseException so a routine's `except Exception` cannot swallow the task limits.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from harness.log import EventLog

DEFAULT_MODEL = "qwen3.5:4b"
OPTIONS = {"temperature": 0, "num_ctx": 16384, "num_predict": 768}
if os.environ.get("STUDENT_NUM_THREAD"):  # Ollama defaults to physical cores; on a 2c/4t VM all 4 is ~15% faster
    OPTIONS["num_thread"] = int(os.environ["STUDENT_NUM_THREAD"])
KEEP_ALIVE = "30m"
# One call can legitimately take minutes on a CPU-only box (a cold 10k-token prompt at ~20 tok/s is ~8 min).
# The task's wall clock (SIGALRM) is the real limit; this only guards against a hung connection.
HTTP_TIMEOUT = float(os.environ.get("STUDENT_HTTP_TIMEOUT", 900))


class TaskStop(BaseException):
    """A hard task limit was hit (wall clock, model-call budget). Ends the task, never caught by routines."""


class DeadlineExceeded(TaskStop):
    pass


class BudgetExceeded(TaskStop):
    pass


class TaskTimeout(TaskStop):
    """Raised asynchronously (SIGALRM) when the task's wall clock runs out mid-call."""


class StudentFormatError(ValueError):
    """The student's structured reply failed validation twice."""


class Diagnosis(BaseModel):
    file: str = Field(description="task-relative path of the file containing the root cause")
    function: str = Field(description="name of the function containing the root cause")
    hypothesis: str = Field(description="one or two sentences: what is wrong and why the tests fail")


class PatchBlock(BaseModel):
    file: str = Field(description="task-relative path of the file to edit")
    search: str = Field(description="exact existing text to replace, copied verbatim including indentation")
    replace: str = Field(description="the replacement text")


FORMATS: dict[str, type[BaseModel]] = {"diagnose": Diagnosis, "patch": PatchBlock}

ASK_SYSTEM = ("You are the reasoning component of a coding agent. Answer the request with ONLY a JSON object "
              "that matches this JSON schema, no prose and no markdown fences:\n{schema}")


def extract_json(text: str) -> str:
    """Strip markdown fences / chatter around a JSON object."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        a, b = text.find("{"), text.rfind("}")
        if a != -1 and b > a:
            text = text[a:b + 1]
    return text


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class Student:
    role = "student"

    def __init__(self, log: EventLog | None = None, *, model: str | None = None, host: str | None = None,
                 client: Any = None, max_calls: int | None = None, deadline: float | None = None):
        self.log = log
        self.model = model or os.environ.get("STUDENT_MODEL") or DEFAULT_MODEL
        if client is None:
            import ollama
            client = ollama.Client(host=host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434",
                                   timeout=HTTP_TIMEOUT)
        self.client = client
        self.calls = 0
        self.max_calls = max_calls
        self.deadline = deadline  # time.monotonic() value

    # ---- public API ----------------------------------------------------------------------------

    def chat(self, messages: list[dict], tools: list[dict] | None = None, *, purpose: str = "chat") -> dict:
        """One tool-calling turn. Returns {content, tool_calls:[{name, arguments}], message}."""
        resp = self._call(messages, purpose=purpose, tools=tools or None)
        msg = _get(resp, "message") or {}
        content = _get(msg, "content") or ""
        calls = []
        for tc in _get(msg, "tool_calls") or []:
            fn = _get(tc, "function") or {}
            args = _get(fn, "arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_raw": args}
            calls.append({"name": _get(fn, "name") or "", "arguments": dict(args)})
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if calls:
            message["tool_calls"] = [{"function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]
        return {"content": content, "tool_calls": calls, "message": message}

    def ask(self, purpose: str, prompt: str, schema: type[BaseModel] | None = None) -> dict:
        """Structured semantic call. Validates against `schema` (defaults: FORMATS[purpose]); re-asks once."""
        schema = schema or FORMATS.get(purpose)
        if schema is None:
            raise ValueError(f"no schema given and no fixed format named {purpose!r} (known: {sorted(FORMATS)})")
        json_schema = schema.model_json_schema()
        messages = [
            {"role": "system", "content": ASK_SYSTEM.format(schema=json.dumps(json_schema))},
            {"role": "user", "content": prompt},
        ]
        error = ""
        for attempt in range(2):
            resp = self._call(messages, purpose=purpose if attempt == 0 else f"{purpose}:retry", format=json_schema)
            content = _get(_get(resp, "message") or {}, "content") or ""
            try:
                return schema.model_validate_json(extract_json(content)).model_dump()
            except ValidationError as e:
                error = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'reply'}: {x['msg']}" for x in e.errors())[:800]
                messages += [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"That reply was invalid ({error}). "
                                                f"Reply again with ONLY a valid JSON object matching the schema."},
                ]
        raise StudentFormatError(f"{purpose}: invalid structured reply after retry: {error}")

    # ---- plumbing ------------------------------------------------------------------------------

    def _call(self, messages: list[dict], *, purpose: str, **kw: Any) -> Any:
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise DeadlineExceeded("wall-clock limit reached before student call")
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise BudgetExceeded(f"student call budget ({self.max_calls}) exhausted")
        self.calls += 1
        t0 = time.monotonic()
        try:
            resp = self.client.chat(model=self.model, messages=messages, think=False, options=dict(OPTIONS),
                                    keep_alive=KEEP_ALIVE, **kw)
        except BaseException as e:  # timed out / interrupted: still a model call, and stop the server generating
            self._drop_connection()
            if self.log:
                self.log.emit("model.call", model=self.model, role=self.role, purpose=purpose, promptTokens=0,
                              outTokens=0, ms=int((time.monotonic() - t0) * 1000), error=type(e).__name__)
            raise
        ms = int((time.monotonic() - t0) * 1000)
        if self.log:
            self.log.emit("model.call", model=self.model, role=self.role, purpose=purpose,
                          promptTokens=_get(resp, "prompt_eval_count") or 0, outTokens=_get(resp, "eval_count") or 0,
                          ms=ms, doneReason=_get(resp, "done_reason"),
                          prompt=prompt_excerpt(messages), response=response_excerpt(resp))
        return resp

    def _drop_connection(self) -> None:
        """Close the HTTP connection so Ollama cancels an abandoned generation instead of finishing it."""
        http = getattr(self.client, "_client", None)
        if http is not None and hasattr(http, "close"):
            try:
                http.close()
                import ollama
                if isinstance(self.client, ollama.Client):
                    self.client = ollama.Client(host=str(http.base_url), timeout=HTTP_TIMEOUT)
            except Exception:
                pass


# What the GUI shows for each call: the newest message the model saw and what it answered (trimmed).
PROMPT_EXCERPT, RESPONSE_EXCERPT = 1200, 2000


def prompt_excerpt(messages: list[dict]) -> str:
    if not messages:
        return ""
    last = messages[-1]
    text = str(last.get("content") or "")
    return f"[{last.get('role', '?')}] " + (text if len(text) <= PROMPT_EXCERPT else "…" + text[-PROMPT_EXCERPT:])


def response_excerpt(resp: Any) -> str:
    message = _get(resp, "message") or {}
    text = str(_get(message, "content") or "").strip()
    for call in _get(message, "tool_calls") or []:
        fn = _get(call, "function") or {}
        text += f"\n→ {_get(fn, 'name')}({json.dumps(dict(_get(fn, 'arguments') or {}), ensure_ascii=False)})"
    text = text.strip()
    return text if len(text) <= RESPONSE_EXCERPT else text[:RESPONSE_EXCERPT] + "…"
