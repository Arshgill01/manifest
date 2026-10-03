"""Student client against a fake Ollama client: settings, logging, structured asks, limits."""

import time

import pytest
from pydantic import BaseModel

from harness.log import EventLog
from harness.student import (BudgetExceeded, DeadlineExceeded, Student, StudentFormatError, TaskStop,
                             extract_json)


class FakeOllama:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def chat(self, **kw):
        self.requests.append(kw)
        r = self.replies.pop(0)
        msg = r if isinstance(r, dict) else {"role": "assistant", "content": r}
        return {"message": msg, "prompt_eval_count": 100, "eval_count": 7, "done_reason": "stop"}


def test_settings_and_model_call_event():
    log = EventLog()
    fake = FakeOllama(["hello"])
    s = Student(log, client=fake)
    out = s.chat([{"role": "user", "content": "hi"}], [{"type": "function"}])
    req = fake.requests[0]
    assert req["model"] == "qwen3.5:4b" and req["think"] is False
    assert req["options"] == {"temperature": 0, "num_ctx": 16384, "num_predict": 768}
    assert out == {"content": "hello", "tool_calls": [], "message": {"role": "assistant", "content": "hello"}}
    ev = log.events[-1]
    assert ev["type"] == "model.call" and ev["role"] == "student" and ev["purpose"] == "chat"
    assert (ev["promptTokens"], ev["outTokens"]) == (100, 7) and isinstance(ev["ms"], int)
    assert s.calls == 1


def test_chat_tool_calls_normalised():
    fake = FakeOllama([{"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "read_file", "arguments": {"path": "a.py"}}},
        {"function": {"name": "bash", "arguments": '{"cmd": "ls"}'}},
    ]}])
    out = Student(client=fake).chat([], [])
    assert out["tool_calls"] == [{"name": "read_file", "arguments": {"path": "a.py"}},
                                 {"name": "bash", "arguments": {"cmd": "ls"}}]
    assert out["message"]["tool_calls"][0] == {"function": {"name": "read_file", "arguments": {"path": "a.py"}}}


def test_ask_fixed_formats_and_schema_passed():
    fake = FakeOllama(['```json\n{"file": "src/m.py", "function": "f", "hypothesis": "off by one"}\n```'])
    log = EventLog()
    d = Student(log, client=fake).ask("diagnose", "why?")
    assert d == {"file": "src/m.py", "function": "f", "hypothesis": "off by one"}
    assert fake.requests[0]["format"]["required"] == ["file", "function", "hypothesis"]
    assert log.events[-1]["purpose"] == "diagnose"


def test_ask_reasks_once_with_error_then_succeeds():
    fake = FakeOllama(['{"file": "a.py"}', '{"file": "a.py", "search": "x", "replace": "y"}'])
    log = EventLog()
    s = Student(log, client=fake)
    assert s.ask("patch", "fix it") == {"file": "a.py", "search": "x", "replace": "y"}
    retry = fake.requests[1]["messages"]
    assert retry[-1]["role"] == "user" and "invalid" in retry[-1]["content"] and "search" in retry[-1]["content"]
    assert [e["purpose"] for e in log.events] == ["patch", "patch:retry"] and s.calls == 2


def test_ask_gives_up_after_one_retry():
    s = Student(client=FakeOllama(["nope", "still nope"]))
    with pytest.raises(StudentFormatError):
        s.ask("diagnose", "?")
    assert s.calls == 2


def test_ask_custom_schema_and_unknown_purpose():
    class Verdict(BaseModel):
        ok: bool

    assert Student(client=FakeOllama(['{"ok": true}'])).ask("judge", "?", Verdict) == {"ok": True}
    with pytest.raises(ValueError):
        Student(client=FakeOllama([])).ask("judge", "?")


def test_limits_raise_taskstop_not_exception():
    s = Student(client=FakeOllama(["a", "b"]), max_calls=1)
    s.chat([])
    with pytest.raises(BudgetExceeded):
        s.chat([])
    s = Student(client=FakeOllama(["a"]), deadline=time.monotonic() - 1)
    with pytest.raises(DeadlineExceeded):
        s.chat([])
    assert not issubclass(TaskStop, Exception)  # routines' `except Exception` can't swallow task limits


def test_extract_json():
    assert extract_json('Sure! {"a": 1} hope that helps') == '{"a": 1}'
    assert extract_json("<think>hmm</think>\n{\"a\": 2}") == '{"a": 2}'


def test_interrupted_call_still_logged():
    class Hangs:
        def chat(self, **kw):
            raise TimeoutError("read timed out")

    log = EventLog()
    s = Student(log, client=Hangs())
    with pytest.raises(TimeoutError):
        s.chat([])
    ev = log.events[-1]
    assert ev["type"] == "model.call" and ev["error"] == "TimeoutError" and s.calls == 1
