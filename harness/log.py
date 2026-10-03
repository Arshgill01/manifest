"""Event log writer. The only way anything writes `.manifest/runs/*.jsonl` (CONTRACT.md part 1)."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / ".manifest" / "runs"

EVENT_TYPES = {
    "run.start", "task.start", "task.end", "routine.call", "model.call", "tool.call",
    "growth.proposal", "warden.manifest", "warden.block", "gate.result",
    "eval.heldout", "run.end",
}


def now_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_run_id(label: str) -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{label}"


class EventLog:
    """Append-only JSONL writer with ambient round/taskId/split context.

    log = EventLog.create("growth")
    log.emit("run.start", mode="manifest", student="qwen3.5:4b", teacher="...", online=True)
    with log.scope(round=1, taskId="ledgerly-03", split="train"):
        log.emit("routine.call", routine="start", summary="listed 9 files", ms=12)
    """

    def __init__(self, path: Path | None = None, *, round: int = 0, keep_in_memory: bool = True):
        self.path = Path(path) if path else None
        self.ctx: dict[str, Any] = {"round": round, "taskId": None, "split": None}
        self.events: list[dict] = [] if keep_in_memory else None  # type: ignore[assignment]
        self._lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def create(cls, label: str, **kw: Any) -> "EventLog":
        return cls(RUNS_DIR / f"{new_run_id(label)}.jsonl", **kw)

    @property
    def run_id(self) -> str | None:
        return self.path.stem if self.path else None

    def set(self, **ctx: Any) -> None:
        self.ctx.update(ctx)

    @contextmanager
    def scope(self, **ctx: Any) -> Iterator["EventLog"]:
        saved = dict(self.ctx)
        self.ctx.update(ctx)
        try:
            yield self
        finally:
            self.ctx = saved

    def emit(self, type: str, **fields: Any) -> dict:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type!r} (see CONTRACT.md)")
        event = {"ts": now_ts(), "type": type, **self.ctx, **fields}
        line = json.dumps(event, default=str, ensure_ascii=False)
        with self._lock:
            if self.events is not None:
                self.events.append(event)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    f.flush()
        return event

    def for_task(self, task_id: str, round: int | None = None) -> list[dict]:
        return [
            e for e in (self.events or [])
            if e.get("taskId") == task_id and (round is None or e.get("round") == round)
        ]


def read_events(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
