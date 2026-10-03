"""Controller state (SPEC 4.3, CONTRACT 2.3). JSON-serialisable so routines can run out-of-process.

Nested records are plain dicts so they slot straight in from `Tools.run_tests()`:
  failures      [{test, error, frames: [{file, line, function}]}]      (innermost frame last)
  suspect       {file, line, function}
  patches       [{file, search, replace, ok}]
  last_full_run {passed, failed}

Routines may set `state.summary` (one line, shown in the `routine.call` event) and may add their own
fields: extra attributes are allowed and serialised. The controller owns `steps`, `model_calls`,
`routine_runs` and `history`; routines should not change those.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class State(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_dir: str
    task: str = ""                                   # TASK.md text
    files: list[str] = Field(default_factory=list)   # task-relative paths
    test_output: str = ""                            # last pytest output (truncated)
    failures: list[dict[str, Any]] = Field(default_factory=list)
    suspect: dict[str, Any] | None = None
    context_snippet: str = ""
    patches: list[dict[str, Any]] = Field(default_factory=list)
    last_full_run: dict[str, Any] | None = None
    done: bool = False                               # set by a routine when it believes the task is finished
    steps: int = 0
    max_steps: int = 12
    model_calls: int = 0
    summary: str = ""                                # routine's one-line summary of its last run (consumed by controller)
    routine_runs: dict[str, int] = Field(default_factory=dict)   # name -> times run this task
    history: list[dict[str, Any]] = Field(default_factory=list)  # [{step, routine, summary}]
    messages: list[dict[str, Any]] = Field(default_factory=list) # ask-student conversation
    notes: dict[str, Any] = Field(default_factory=dict)          # free scratch space for routines

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, text: str) -> "State":
        return cls.model_validate_json(text)

    @property
    def steps_left(self) -> int:
        return max(0, self.max_steps - self.steps)
