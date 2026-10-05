import json
from types import SimpleNamespace

import pytest

from harness.log import EventLog
from harness.teacher import (
    FAKE_PROPOSALS,
    Prices,
    Teacher,
    TeacherError,
    TeacherOutputError,
    check_routine_source,
    parse_json_object,
)


class FakeClient:
    """Mimics openai.OpenAI().chat.completions.create; replays canned contents."""

    def __init__(self, contents, *, usage=None, raise_exc=None):
        self.contents = list(contents)
        self.usage = usage or {"prompt_tokens": 1000, "completion_tokens": 200, "prompt_cache_hit_tokens": 400}
        self.raise_exc = raise_exc
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        if self.raise_exc:
            raise self.raise_exc
        content = self.contents.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(**self.usage),
        )


def make(contents, **kw):
    log = EventLog()
    client = FakeClient(contents, **kw)
    t = Teacher(log, client=client, model="deepseek-test", prices=Prices(1.0, 0.1, 2.0))
    return t, client, log


CONTEXT = {"round": 1, "api": "API", "registry": [], "failed_traces": [], "history": []}
GOOD = json.dumps(FAKE_PROPOSALS[2])


def test_valid_first_try_settings_and_cost():
    t, client, log = make([GOOD])
    p = t.propose(CONTEXT)
    assert p["name"] == "trace-to-source"
    assert set(p) == {"name", "rationale", "trigger_description", "routine_py", "skill_md", "requested_permissions"}
    req = client.requests[0]
    assert req["temperature"] == 0 and req["model"] == "deepseek-test"
    assert req["response_format"] == {"type": "json_object"}
    (ev,) = [e for e in log.events if e["type"] == "model.call"]
    assert ev["role"] == "teacher" and ev["purpose"] == "propose"
    assert ev["promptTokens"] == 1000 and ev["outTokens"] == 200 and ev["cacheHitTokens"] == 400
    # 600 miss * 1.0 + 400 hit * 0.1 + 200 out * 2.0 per 1M
    assert ev["costUsd"] == pytest.approx((600 + 40 + 400) / 1e6)
    assert t.cost_usd == pytest.approx(ev["costUsd"]) and t.calls == 1


def test_invalid_then_valid_retries_once_with_error():
    t, client, _ = make(["not json at all", GOOD])
    assert t.propose(CONTEXT)["name"] == "trace-to-source"
    assert len(client.requests) == 2
    retry_msgs = client.requests[1]["messages"]
    assert retry_msgs[-2]["role"] == "assistant" and retry_msgs[-2]["content"] == "not json at all"
    assert "invalid" in retry_msgs[-1]["content"]


def test_invalid_twice_raises():
    bad = dict(FAKE_PROPOSALS[0], routine_py="NAME = 'x'\n")
    t, client, _ = make([json.dumps(bad), json.dumps(bad)])
    with pytest.raises(TeacherOutputError):
        t.propose(CONTEXT)
    assert len(client.requests) == 2


@pytest.mark.parametrize(
    "patch, msg",
    [
        ({"name": "Bad_Name"}, "kebab-case"),
        ({"name": "ask-student"}, "seed routine"),
        ({"rationale": "  "}, "rationale"),
    ],
)
def test_proposal_validation(patch, msg):
    bad = json.dumps(dict(FAKE_PROPOSALS[2], **patch))
    t, client, _ = make([bad, bad])
    with pytest.raises(TeacherOutputError, match=msg):
        t.propose(CONTEXT)


def test_routine_source_checks():
    ok = 'NAME = "x"\ndef applies(state):\n    return True\ndef run(state, tools, student):\n    return state\n'
    check_routine_source(ok, "x")
    with pytest.raises(ValueError, match="NAME"):
        check_routine_source(ok, "y")
    with pytest.raises(ValueError, match="lines"):
        check_routine_source(ok + "\n".join(f"a{i} = {i}" for i in range(160)), "x")
    with pytest.raises(ValueError, match="parse"):
        check_routine_source("def (:", "x")
    with pytest.raises(ValueError, match="run"):
        check_routine_source(ok.replace("tools, student", "tools"), "x")


def test_json_fences_and_non_object():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json_object("[1, 2]")


def test_summarize_code():
    t, _, log = make([json.dumps({"findings": ["reads ~/.ssh/id_ed25519", "posts it to localhost:9999"]})])
    assert t.summarize_code("import os") == ["reads ~/.ssh/id_ed25519", "posts it to localhost:9999"]
    assert log.events[-1]["purpose"] == "warden-summarize"


def test_api_failure_is_teacher_error_not_retried():
    t, client, _ = make([], raise_exc=ConnectionError("offline"))
    with pytest.raises(TeacherError) as ei:
        t.propose(CONTEXT)
    assert not isinstance(ei.value, TeacherOutputError)
    assert len(client.requests) == 1


def test_missing_config(monkeypatch):
    monkeypatch.setattr("harness.teacher.load_env", lambda: None)
    monkeypatch.delenv("TEACHER_MODEL", raising=False)
    with pytest.raises(TeacherError, match="TEACHER_MODEL"):
        Teacher(EventLog())
    monkeypatch.setenv("TEACHER_MODEL", "m")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(TeacherError, match="DEEPSEEK_API_KEY"):
        Teacher(EventLog())


def test_fake_proposals_are_valid():
    from harness.teacher import Proposal

    for p in FAKE_PROPOSALS:
        Proposal.model_validate(p)


def test_truncated_answer_is_retried_without_resending_it_and_effort_is_low():
    from types import SimpleNamespace as NS
    from harness.log import EventLog
    from harness.teacher import Teacher
    good = json.dumps({"findings": ["reads nothing"]})
    replies = [("", "length"), (good, "stop")]
    seen = []

    class C:
        def create(self, **kw):
            seen.append(kw)
            text, fin = replies[len(seen) - 1]
            return NS(choices=[NS(message=NS(content=text), finish_reason=fin)],
                      usage=NS(prompt_tokens=10, completion_tokens=5, prompt_cache_hit_tokens=0))

    t = Teacher(EventLog(), client=NS(chat=NS(completions=C())), model="m")
    assert t.summarize_code("x = 1") == ["reads nothing"]
    assert seen[0]["reasoning_effort"] == "low"
    assert all(m["role"] != "assistant" for m in seen[1]["messages"]) and "cut off" in seen[1]["messages"][-1]["content"]


def test_comments_and_docstrings_do_not_count_and_fences_are_stripped():
    from harness.teacher import Change
    body = 'NAME = "x"\n"""doc\n' + "more doc\n" * 200 + '"""\n' + "# c\n" * 50 + \
        "def applies(state):\n    return True\n\ndef run(state, tools, student):\n    return state\n"
    with pytest.raises(ValueError, match="hard ceiling"):
        check_routine_source(body, "x")            # >300 total lines
    small = 'NAME = "x"\n"""doc\n' + "more doc\n" * 100 + '"""\n' + "# c\n" * 40 + \
        "def applies(state):\n    return True\n\ndef run(state, tools, student):\n    return state\n"
    check_routine_source(small, "x")               # 150+ raw lines but only 5 code lines
    with pytest.raises(ValueError, match="line 1: '/\\* banner \\*/'"):
        check_routine_source("/* banner */\n" + small, "x")
    c = Change(name="x", trigger_description="t", routine_py="```python\n" + small + "```", skill_md="s")
    assert c.routine_py.startswith('NAME = "x"')
