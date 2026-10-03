"""Gate (SPEC §5.4): a candidate routine is kept iff the gate split improves and nothing regresses.

Accept iff  gateAfter > gateBefore,  or  gateAfter == gateBefore with avg model calls down ≥ 20%,
       and  no gate task that passed before fails after.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Callable

from harness.log import EventLog

MIN_CALL_DROP = 0.20


def as_split_result(obj: Any) -> dict:
    """Normalise whatever run_split returned (dict / pydantic / dataclass) into the CONTRACT 2.2 dict shape."""
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(by_alias=True)
    elif is_dataclass(obj) and not isinstance(obj, type):
        obj = asdict(obj)
    d = dict(obj)
    results = []
    for r in d.get("results", []):
        if hasattr(r, "model_dump"):
            r = r.model_dump(by_alias=True)
        elif is_dataclass(r) and not isinstance(r, type):
            r = asdict(r)
        r = dict(r)
        if "pass" not in r and "pass_" in r:
            r["pass"] = r.pop("pass_")
        results.append(r)
    d["results"] = results
    d.setdefault("total", len(results))
    d.setdefault("passed", sum(1 for r in results if r.get("pass")))
    if "avgModelCalls" not in d:
        d["avgModelCalls"] = sum(r.get("modelCalls", 0) for r in results) / len(results) if results else 0.0
    return d


def passing_ids(result: dict) -> set[str]:
    return {r["taskId"] for r in result.get("results", []) if r.get("pass")}


@dataclass
class GateDecision:
    accepted: bool
    gateBefore: int
    gateAfter: int | None
    regressions: list[str] = field(default_factory=list)
    modelCallsBefore: float = 0.0
    modelCallsAfter: float | None = None
    rejectReason: str | None = None
    gateTotal: int = 0

    def event_fields(self) -> dict:
        d = asdict(self)
        for k in ("modelCallsBefore", "modelCallsAfter"):
            if d[k] is not None:
                d[k] = round(float(d[k]), 3)
        return d


def decide(before: dict, after: dict, *, min_call_drop: float = MIN_CALL_DROP) -> GateDecision:
    before, after = as_split_result(before), as_split_result(after)
    b_pass, a_pass = int(before["passed"]), int(after["passed"])
    b_calls, a_calls = float(before["avgModelCalls"]), float(after["avgModelCalls"])
    regressions = sorted(passing_ids(before) - passing_ids(after))

    reason = None
    if regressions:
        reason = f"regression on {len(regressions)} previously passing gate task(s)"
    elif a_pass > b_pass:
        pass
    elif a_pass == b_pass:
        drop = (b_calls - a_calls) / b_calls if b_calls > 0 else 0.0
        if drop < min_call_drop:
            reason = f"gate flat ({a_pass}/{after['total']}) and model calls down only {drop:.0%} (< {min_call_drop:.0%})"
    else:
        reason = f"gate went down ({b_pass} → {a_pass})"

    return GateDecision(
        accepted=reason is None,
        gateBefore=b_pass,
        gateAfter=a_pass,
        regressions=regressions,
        modelCallsBefore=b_calls,
        modelCallsAfter=a_calls,
        rejectReason=reason,
        gateTotal=int(after["total"]),
    )


def emit_gate_result(log: EventLog, routine: str, decision: GateDecision) -> dict:
    with log.scope(taskId=None, split="gate"):
        return log.emit("gate.result", routine=routine, **decision.event_fields())


def reject_before_gate(log: EventLog, routine: str, before: dict, reason: str) -> GateDecision:
    """A candidate stopped before the gate ran (e.g. Warden verdict 'dangerous'): still log a gate.result."""
    before = as_split_result(before)
    d = GateDecision(
        accepted=False,
        gateBefore=int(before["passed"]),
        gateAfter=None,
        modelCallsBefore=float(before["avgModelCalls"]),
        modelCallsAfter=None,
        rejectReason=reason,
        gateTotal=int(before["total"]),
    )
    emit_gate_result(log, routine, d)
    return d


def run_gate(
    *,
    routine: str,
    registry: str,
    before: dict,
    run_split: Callable[..., Any],
    log: EventLog,
    round: int,
    task_ids: list[str] | None = None,
    mode: str = "manifest",
) -> tuple[GateDecision, dict]:
    """Run the gate split with the candidate registry, decide, and log `gate.result`."""
    after = as_split_result(run_split("gate", mode=mode, round=round, log=log, registry=registry, task_ids=task_ids))
    decision = decide(before, after)
    emit_gate_result(log, routine, decision)
    return decision, after
