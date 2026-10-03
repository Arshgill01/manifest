"""Local stand-ins for other tracks' seams, coded to CONTRACT.md signatures.

Used by grow.py when `--stub-runner` is set (or the real module isn't merged yet) and by the tests.
Nothing here touches Ollama, the network, or real task directories. Results are deterministic:
a task passes if a hash of (task id, routine source) says one of the grown routines "fixes" it, so
adding a routine never regresses a task but editing one can.

- run_split / run_task  ≈ growth.eval.run_split (A) / harness.run.run_task (B)
- warden_scan / warden_build ≈ warden.scan.scan / warden.manifest.build (D)
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from harness.log import ROOT, EventLog

DOMAINS = ("ledgerly", "stockroom", "slotbook", "ratekeeper", "csvflow")
SHAPES = ("deep-call-chain", "one-root-many-failures", "regression-trap", "misleading-surface")

STUB_SPLITS: dict[str, Any] = {
    "seed": 1337,
    "train": [f"{d}-{i:02d}" for d in DOMAINS[:4] for i in (1, 2, 3)],
    "gate": [f"{d}-{i:02d}" for d in DOMAINS[:3] for i in (4, 5)],
    "heldout": [f"{d}-{i:02d}" for d in DOMAINS[:3] for i in (6, 7)] + ["csvflow-01", "csvflow-02"],
    "novelDomain": "csvflow",
}


def _h(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else ROOT / path


def grown_fingerprints(registry: str | None) -> list[str]:
    if not registry or not Path(registry).exists():
        return []
    fps = []
    for entry in json.loads(Path(registry).read_text()):
        if entry.get("source") != "grown":
            continue
        src = _resolve(entry["path"]) / "routine.py"
        body = src.read_text() if src.exists() else entry["name"]
        fps.append(hashlib.sha256(body.encode()).hexdigest()[:16])
    return fps


def _task_outcome(task_id: str, mode: str, fps: list[str]) -> tuple[bool, int]:
    base = _h("base", mode, task_id) % (7 if mode == "baseline" else 6) == 0
    fixed = any(_h(task_id, fp) % 3 == 0 for fp in fps)
    calls = max(2, 7 + _h("calls", task_id) % 5 - 2 * len(fps))
    return base or fixed, calls


def run_task(
    workdir: Path, *, mode: str, log: EventLog, registry: str | None = None,
    max_steps: int = 12, max_seconds: int = 120, executor: Any = None,
) -> dict:
    task_id = Path(workdir).name
    domain = task_id.rsplit("-", 1)[0]
    fps = grown_fingerprints(registry) if mode == "manifest" else []
    ok, calls = _task_outcome(task_id, mode, fps)
    routine_calls = 0
    if mode == "manifest":
        log.emit("routine.call", routine="start", summary=f"read TASK.md, listed files of {task_id}", ms=3, source="seed")
        routine_calls += 1
    log.emit("tool.call", tool="run_tests", args={}, ok=True, summary=f"{task_id}: 4 failed, 22 passed")
    for i in range(min(calls, max_steps)):
        if mode == "manifest":
            log.emit("routine.call", routine="ask-student", summary="student picks a tool", ms=2, source="seed")
            routine_calls += 1
        log.emit("model.call", model="stub-student", role="student", purpose="chat" if mode == "baseline" else "ask",
                 promptTokens=1800 + 40 * i, outTokens=60, ms=1)
        log.emit("tool.call", tool="read_file", args={"path": f"src/{domain}/core.py"}, ok=True,
                 summary=f"read src/{domain}/core.py for {task_id}")
    return {"steps": min(calls, max_steps), "modelCalls": calls, "routineCalls": routine_calls, "selfReportedDone": ok}


def run_split(
    split: str, *, mode: str, round: int, log: EventLog,
    registry: str | None = None, task_ids: list[str] | None = None,
) -> dict:
    ids = list(task_ids) if task_ids is not None else list(STUB_SPLITS[split])
    fps = grown_fingerprints(registry) if mode == "manifest" else []
    results = []
    for tid in ids:
        with log.scope(round=round, taskId=tid, split=split):
            start = log.emit("task.start", domain=tid.rsplit("-", 1)[0], bugShape=SHAPES[_h("shape", tid) % len(SHAPES)], mode=mode)
            n0 = len(log.events)
            info = run_task(Path(f"stub/{tid}"), mode=mode, log=log, registry=registry)
            passed, _ = _task_outcome(tid, mode, fps)
            end = log.emit("task.end", **{"pass": passed}, steps=info["steps"], modelCalls=info["modelCalls"],
                           routineCalls=info["routineCalls"], ms=10)
            events = [start, *log.events[n0:]]
        results.append({"taskId": tid, "pass": passed, "steps": info["steps"], "modelCalls": info["modelCalls"],
                        "routineCalls": info["routineCalls"], "ms": 10, "events": events})
    passed_n = sum(r["pass"] for r in results)
    avg = sum(r["modelCalls"] for r in results) / len(results) if results else 0.0
    if split == "heldout":
        with log.scope(round=round, taskId=None, split="heldout"):
            log.emit("eval.heldout", passed=passed_n, total=len(results), avgModelCalls=round_(avg))
    return {"split": split, "passed": passed_n, "total": len(results), "avgModelCalls": avg, "results": results}


def round_(x: float) -> float:
    return round(x, 3)


# --------------------------------------------------------------------------- Warden stand-in

_RULES: list[tuple[str, str, str]] = [
    ("network", "high", r"\b(?:import|from)\s+(?:socket|urllib|requests|http|httpx|aiohttp)\b|\b(?:curl|wget)\b"),
    ("shell-subprocess", "high", r"\bsubprocess\.\w+\([^)]*shell\s*=\s*True|\bos\.(?:system|popen)\s*\("),
    ("dynamic-exec", "high", r"\b(?:eval|exec)\s*\(|b64decode|__import__\s*\("),
    ("outside-path", "high", r"""['"](?:~|/Users|/home|/etc|\.\./)|expanduser\("""),
    ("env-read", "high", r"\bos\.environ\b|\bgetenv\s*\(|['\"]\.env['\"]"),
    ("subprocess", "medium", r"\bimport\s+subprocess\b|\bfrom\s+subprocess\b"),
]

DEFAULT_MANIFEST = {"read": ["**"], "write": ["src/**"], "commands": ["python -m pytest"], "network": False}


def warden_scan(path: Path, teacher: Any = None) -> list[dict]:
    path = Path(path)
    files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
    findings = []
    for f in files:
        for lineno, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            for rule, sev, pat in _RULES:
                if re.search(pat, line):
                    findings.append({"rule": rule, "severity": sev, "file": f.name, "line": lineno, "detail": line.strip()[:160]})
        if teacher is not None and hasattr(teacher, "summarize_code"):
            for s in teacher.summarize_code(f.read_text(errors="replace")):
                findings.append({"rule": "teacher-summary", "severity": "info", "file": f.name, "line": 0, "detail": s})
    return findings


def warden_build(skill_dir: Path, requested: dict | None, findings: list) -> dict:
    requested = requested or {}
    findings = list(findings)
    if requested.get("network"):
        findings.append({"rule": "requested-network", "severity": "high", "file": "", "line": 0, "detail": "asked for network access"})
    for g in requested.get("write") or []:
        if not g.startswith("src/"):
            findings.append({"rule": "requested-write", "severity": "high", "file": "", "line": 0, "detail": f"asked to write {g}"})
    sev = {f.get("severity") for f in findings}
    verdict = "dangerous" if "high" in sev else "review" if "medium" in sev else "ok"
    return {"skill": Path(skill_dir).name, **DEFAULT_MANIFEST, "findings": findings, "verdict": verdict}
