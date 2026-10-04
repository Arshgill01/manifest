"""Growth loop (SPEC §5): per round, train → failed traces → teacher proposal → Warden → gate → accept → held-out.

    uv run python -m growth.grow                                  # the real run (DeepSeek + Ollama)
    uv run python -m growth.grow --fake-teacher --stub-runner     # offline dry run, no models at all
    uv run python -m growth.grow --train-tasks a,b,c --gate-tasks d,e --rounds 1

Guarantees:
- The teacher context is built from train-split events only; held-out ids and the novel domain are
  checked against every context before it is sent (`LeakError`).
- Anything produced by the fake teacher or judged by the stub runner goes to a scratch root under
  .manifest/work/, never to routines/grown/ or skills/.
- One JSONL event log for the whole run; ends with `run.end` {heldoutByRound, avgModelCallsByRound, ...}.
"""

from __future__ import annotations

import argparse
import ast
import functools
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from growth import stubs
from growth.gate import as_split_result, reject_before_gate, run_gate
from growth.traces import compress_failed_traces
from harness.log import ROOT, EventLog, RUNS_DIR, new_run_id
from harness.teacher import SEED_NAMES, FakeTeacher, Teacher, TeacherError, TeacherOutputError

REGISTRY = ROOT / "routines" / "registry.json"
GROWN_DIR = ROOT / "routines" / "grown"
SKILLS_DIR = ROOT / "skills"
WORK_DIR = ROOT / ".manifest" / "work"
SPLITS = ROOT / "tasks" / "splits.json"

SEED_REGISTRY = [
    {"name": "start", "path": "routines/seed/start", "source": "seed"},
    {"name": "ask-student", "path": "routines/seed/ask-student", "source": "seed"},
]


class LeakError(RuntimeError):
    """Held-out material was about to reach the teacher."""


def say(msg: str) -> None:
    print(f"[grow] {msg}", flush=True)


# --------------------------------------------------------------------------- paths + registry


@dataclass
class Paths:
    registry: Path
    grown: Path
    skills: Path
    staging: Path
    dry: bool

    @classmethod
    def real(cls, run_id: str) -> "Paths":
        return cls(REGISTRY, GROWN_DIR, SKILLS_DIR, WORK_DIR / "candidates" / run_id, dry=False)

    @classmethod
    def scratch(cls, run_id: str, source_registry: Path | None = None, root: Path | None = None) -> "Paths":
        source_registry = source_registry or REGISTRY
        base = (root or WORK_DIR) / f"dry-run-{run_id}"
        p = cls(base / "routines" / "registry.json", base / "routines" / "grown", base / "skills", base / "candidates", dry=True)
        p.registry.parent.mkdir(parents=True, exist_ok=True)
        save_registry(p.registry, load_registry(source_registry) if source_registry.exists() else SEED_REGISTRY)
        return p


def rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(Path(path).resolve())


def resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else ROOT / path


def load_registry(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_registry(path: Path, entries: list[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")


def with_routine(entries: list[dict], entry: dict) -> list[dict]:
    """Replace a grown routine of the same name in place, else insert immediately before `ask-student`."""
    out = [dict(e) for e in entries]
    for i, e in enumerate(out):
        if e["name"] == entry["name"]:
            if e.get("source") != "grown":
                raise ValueError(f"refusing to replace non-grown routine {e['name']!r}")
            out[i] = entry
            return out
    idx = next((i for i, e in enumerate(out) if e["name"] == "ask-student"), len(out))
    out.insert(idx, entry)
    return out


def registry_key(entries: list[dict]) -> str:
    h = hashlib.sha256(json.dumps(entries, sort_keys=True).encode())
    for e in entries:
        src = resolve(e["path"]) / "routine.py"
        if src.exists():
            h.update(src.read_bytes())
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------- teacher context


def _signatures(path: Path, class_name: str) -> str:
    """`def` lines + first docstring line for the public methods of one class, so the teacher codes to the real API."""
    if not path.exists():
        return ""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and not fn.name.startswith("_"):
                    sig = f"{class_name.lower()}.{fn.name}({ast.unparse(fn.args)})"
                    if fn.returns is not None:
                        sig += f" -> {ast.unparse(fn.returns)}"
                    doc = (ast.get_docstring(fn) or "").strip().splitlines()
                    lines.append(f"  {sig}" + (f"   # {doc[0]}" if doc else ""))
    return "\n".join(lines)


ROUTINE_API = """\
A routine is one Python module `routine.py`:

    NAME = "kebab-case-name"
    def applies(state) -> bool:              # trigger condition: pure, cheap, no side effects
    def run(state, tools, student) -> state: # deterministic control code; mutate and return the state

Controller loop: pick the FIRST routine in registry order whose applies(state) is True, run it, repeat
until state.done or the budget (12 routine runs and 24 student calls per task). Registry order: `start` first, grown routines
next, `ask-student` (fallback: the student picks a tool, i.e. plain tool-calling) always last.
Routines may run out-of-process under a sandbox, so the state must stay JSON-serialisable.

state (pydantic model) has at least:
  task_dir, test_output, failures: [{test, error, frames: [{file, line, function}]}],
  suspect: {file, line, function}, context_snippet, patches: [], last_full_run: {passed, failed},
  done: bool, steps: int, model_calls: int, notes: dict (free scratch space), routine_runs: {name: count}

Every function you define in a routine is traced (calls, arguments, return values) and shown back to you
in later execution graphs, so small named helpers make failures easy to localise.

tools (each call is checked against the routine's Warden manifest; paths are relative to the task dir):
  tools.list_files()
  tools.read_file(path, start=None, end=None)
  tools.run_tests(selector=None) -> {passed, failed, output, failures: [{test, error, frames: [{file, line, function}]}]}
  tools.edit_file(path, search, replace)   # exact search/replace; tests/** is never writable
  tools.bash(cmd)                          # allowed command prefixes only, e.g. "python -m pytest"

student (local 4B model; ~30-90 s per call on this CPU-only machine, and a fresh long prompt costs more than an
appended one; weak at multi-step planning and long contexts, fine at one focused question):
  student.ask(purpose: str, prompt: str, schema: type[pydantic.BaseModel]) -> dict   # validated, re-asked once
  fixed formats: purpose "diagnose" -> {file, function, hypothesis}; purpose "patch" -> one search/replace block"""


def api_reference() -> str:
    parts = [ROUTINE_API]
    state_src = ROOT / "harness" / "state.py"
    if state_src.exists():
        src = state_src.read_text(encoding="utf-8").splitlines()[:200]
        parts.append("Actual harness/state.py:\n```python\n" + "\n".join(src) + "\n```")
    for fname, cls in (("tools.py", "Tools"), ("student.py", "Student")):
        sigs = _signatures(ROOT / "harness" / fname, cls)
        if sigs:
            parts.append(f"Actual {cls} methods (harness/{fname}):\n{sigs}")
    return "\n\n".join(parts)


def registry_for_teacher(entries: list[dict]) -> list[dict]:
    out = []
    for e in entries:
        src = resolve(e["path"]) / "routine.py"
        code = src.read_text(encoding="utf-8") if src.exists() else "# (source not available)"
        out.append({"name": e["name"], "source": e.get("source", "?"), "code": code})
    return out


def build_teacher_context(round: int, entries: list[dict], traces: list[dict], history: list[dict]) -> dict:
    return {
        "round": round,
        "api": api_reference(),
        "registry": registry_for_teacher(entries),
        "failed_traces": traces,
        "history": history,
    }


def banned_terms(splits: dict) -> list[str]:
    """Strings that must never reach the teacher: every held-out task id and the held-out-only domain."""
    terms = sorted(set(splits.get("heldout", [])) | set(splits.get("heldoutAll", [])))
    novel = splits.get("novelDomain")
    seen = " ".join(splits.get("train", []) + splits.get("gate", []))
    if novel and novel not in seen:
        terms.append(novel)
    return terms


def assert_no_leak(context: dict, terms: list[str]) -> None:
    blob = json.dumps(context, ensure_ascii=False, default=str)
    for t in terms:
        if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w])", blob):
            raise LeakError(f"held-out material {t!r} found in teacher context; refusing to send")


# --------------------------------------------------------------------------- candidates + export


_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


def render_skill_md(proposal: dict, *, round: int, teacher_model: str, manifest: dict | None) -> str:
    """Spec-compliant SKILL.md (agentskills.io): front matter name == dir name, description ≤1024 chars."""
    name, raw = proposal["name"], proposal["skill_md"].strip()
    m = _FRONT.match(raw)
    description, body = "", raw
    if m:
        body = raw[m.end():].strip()
        dm = re.search(r"^description:\s*(.+)$", m.group(1), re.M)
        if dm:
            description = dm.group(1).strip().strip("'\"")
    description = " ".join((description or proposal["trigger_description"]).split())[:1024]
    meta = {"source": "manifest-grown", "round": str(round), "teacher": teacher_model}
    if manifest:
        meta["warden-verdict"] = str(manifest.get("verdict"))
    lines = ["---", f"name: {name}", f"description: {json.dumps(description, ensure_ascii=False)}", "license: MIT", "metadata:"]
    lines += [f"  {k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()]
    lines += ["---", "", body or f"# {name}", ""]
    lines += [
        "## How Manifest uses it",
        "",
        f"Grown by Manifest's growth loop in round {round} (teacher: `{teacher_model}`); never hand-written.",
        "`scripts/routine.py` exports `NAME`, `applies(state)` (trigger) and `run(state, tools, student)`.",
        f"Trigger: {proposal['trigger_description'].strip()}",
        "",
    ]
    if manifest:
        lines += [
            "## Permissions (Warden manifest)",
            "",
            f"- read: {', '.join(manifest.get('read', [])) or '(none)'}",
            f"- write: {', '.join(manifest.get('write', [])) or '(none)'}",
            f"- commands: {', '.join(manifest.get('commands', [])) or '(none)'}",
            f"- network: {str(bool(manifest.get('network'))).lower()}",
            f"- verdict: {manifest.get('verdict')}",
            "",
        ]
    return "\n".join(lines)


def stage_candidate(proposal: dict, staging: Path, *, round: int, teacher_model: str, run_id: str) -> Path:
    d = staging / f"r{round}" / proposal["name"]
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "routine.py").write_text(proposal["routine_py"], encoding="utf-8")
    (d / "SKILL.md").write_text(render_skill_md(proposal, round=round, teacher_model=teacher_model, manifest=None), encoding="utf-8")
    provenance = {k: proposal[k] for k in ("name", "rationale", "trigger_description", "requested_permissions")}
    provenance.update({"round": round, "teacher": teacher_model, "runId": run_id})
    (d / "proposal.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return d


def install(proposal: dict, cand: Path, paths: Paths) -> dict:
    """Accepted: routines/grown/<name>/ + skills/<name>/{SKILL.md, scripts/routine.py, manifest.json}. Returns the registry entry."""
    name = proposal["name"]
    dest, skill = paths.grown / name, paths.skills / name
    for d in (dest, skill):
        if d.exists():
            shutil.rmtree(d)
    shutil.copytree(cand, dest)
    (skill / "scripts").mkdir(parents=True)
    shutil.copy2(cand / "SKILL.md", skill / "SKILL.md")
    shutil.copy2(cand / "routine.py", skill / "scripts" / "routine.py")
    shutil.copy2(cand / "manifest.json", skill / "manifest.json")
    return {"name": name, "path": rel(dest), "source": "grown"}


# --------------------------------------------------------------------------- seams (real or stub)


def resolve_run_split(stub: bool) -> Callable[..., Any]:
    if stub:
        return stubs.run_split
    try:
        from growth.eval import run_split  # track A
    except ImportError as e:
        raise SystemExit(f"growth.eval.run_split not available ({e}); merge track A or pass --stub-runner") from e
    return run_split


def resolve_warden(stub: bool) -> tuple[Callable[..., list], Callable[..., dict], str]:
    if not stub:
        try:
            from warden.manifest import build  # track D
            from warden.scan import scan

            return scan, build, "warden"
        except ImportError as e:
            say(f"warden not merged yet ({e}); using the local stub scanner")
    return stubs.warden_scan, stubs.warden_build, "stub"


def load_splits(stub: bool, profile: str = "core") -> dict:
    """Task ids for one profile of tasks/splits.json (`core` 3/3/3 or `full` 12/6/8)."""
    if SPLITS.exists():
        data = json.loads(SPLITS.read_text(encoding="utf-8"))
        chosen = data.get("profiles", {}).get(profile)
        if chosen is None:
            return data
        # every held-out id of every profile stays banned from the teacher, not just this profile's
        held_all = sorted(set(data.get("heldout", [])).union(*(p.get("heldout", []) for p in data.get("profiles", {}).values())))
        return {**chosen, "novelDomain": data.get("novelDomain"), "heldoutAll": held_all}
    if stub:
        return dict(stubs.STUB_SPLITS)
    raise SystemExit(f"{rel(SPLITS)} missing; merge track A or pass --stub-runner")


# --------------------------------------------------------------------------- the loop


@dataclass
class GrowConfig:
    rounds: int = 4
    fake_teacher: bool = False
    stub_runner: bool = False
    dry_run: bool = False
    train_ids: list[str] | None = None
    gate_ids: list[str] | None = None
    heldout_ids: list[str] | None = None
    max_traces: int = 6
    round0: str = "all"  # all | heldout | none
    heldout_every_round: bool = False
    max_consecutive_rejections: int = 2
    splits: dict | None = None
    log_path: Path | None = None
    label: str = "growth"
    profile: str = "core"     # tasks/splits.json profile
    max_seconds: int = 240    # per-task wall clock, same for baseline and grown harness
    scratch_root: Path | None = None  # default .manifest/work/
    student: str = field(default_factory=lambda: os.environ.get("STUDENT_MODEL", "qwen3.5:4b"))

    @property
    def scratch(self) -> bool:
        return self.dry_run or self.fake_teacher or self.stub_runner


def grow(
    cfg: GrowConfig,
    *,
    teacher: Any = None,
    run_split: Callable[..., Any] | None = None,
    warden: tuple[Callable[..., list], Callable[..., dict]] | None = None,
) -> dict:
    run_id = new_run_id(cfg.label + ("-dryrun" if cfg.scratch else ""))
    paths = Paths.scratch(run_id, root=cfg.scratch_root) if cfg.scratch else Paths.real(run_id)
    log_path = cfg.log_path or ((paths.registry.parent.parent / "run.jsonl") if cfg.scratch else RUNS_DIR / f"{run_id}.jsonl")
    log = EventLog(log_path)

    if run_split is None:
        run_split = resolve_run_split(cfg.stub_runner)
        if not cfg.stub_runner:
            run_split = functools.partial(run_split, max_seconds=cfg.max_seconds)
    if warden is not None:
        scan, build, warden_impl = (*warden, "injected")
    else:
        scan, build, warden_impl = resolve_warden(cfg.stub_runner)
    if teacher is None:
        teacher = FakeTeacher(log) if cfg.fake_teacher else Teacher(log)
    teacher.log = log
    if isinstance(teacher, FakeTeacher) and not paths.dry:
        raise RuntimeError("fake teacher must never write to routines/grown/")
    if not paths.registry.exists():
        raise SystemExit(f"{rel(paths.registry)} missing; merge track B (seed registry) or use --dry-run")

    splits = cfg.splits or load_splits(cfg.stub_runner, cfg.profile)
    train_ids = cfg.train_ids or list(splits["train"])
    gate_ids = cfg.gate_ids or list(splits["gate"])
    heldout_ids = cfg.heldout_ids or list(splits["heldout"])
    leak_terms = banned_terms(splits)
    if set(train_ids) & set(splits.get("heldout", [])):
        raise LeakError("a held-out task was passed as a train task")

    say(f"run {run_id} → {rel(log_path)}" + (f"  (scratch root {rel(paths.registry.parent.parent)})" if paths.dry else ""))
    log.emit("run.start", mode="growth", student=cfg.student, teacher=teacher.model, online=not isinstance(teacher, FakeTeacher),
             dryRun=paths.dry, stubRunner=cfg.stub_runner, wardenImpl=warden_impl,
             trainTasks=len(train_ids), gateTasks=len(gate_ids), heldoutTasks=len(heldout_ids))

    def split_run(split: str, ids: list[str], r: int, registry: Path | None, mode: str = "manifest") -> dict:
        n0 = len(log.events)
        with log.scope(round=r, taskId=None, split=None):
            res = as_split_result(run_split(split, mode=mode, round=r, log=log,
                                            registry=str(registry) if registry else None, task_ids=ids))
        res["_events"] = log.events[n0:]  # this run only; fallback if the runner returns outcomes without events
        say(f"  round {r} {split:<7} {mode:<8} {res['passed']}/{res['total']} pass, {res['avgModelCalls']:.1f} model calls/task")
        return res

    heldout_by_round: list[dict] = []
    if cfg.round0 != "none":
        say("round 0 (baseline; cached by the runner)")
        for split, ids in (("train", train_ids), ("gate", gate_ids), ("heldout", heldout_ids)):
            if cfg.round0 == "all" or split == "heldout":
                res = split_run(split, ids, 0, None, mode="baseline")
                if split == "heldout":
                    heldout_by_round.append({"round": 0, **_heldout_point(res)})

    entries = load_registry(paths.registry)
    cache: dict[tuple[str, str], dict] = {}  # (split, registry key) -> result; registry unchanged ⇒ same harness
    history: list[dict] = []
    accepted: list[str] = []
    rejections = 0
    stop_reason = f"completed {cfg.rounds} rounds"
    last_round = 0

    for r in range(1, cfg.rounds + 1):
        last_round = r
        log.set(round=r, taskId=None, split=None)
        key = registry_key(entries)
        say(f"round {r}  registry: {' → '.join(e['name'] for e in entries)}")

        train = cache.get(("train", key)) or split_run("train", train_ids, r, paths.registry)
        cache[("train", key)] = train
        traces = compress_failed_traces(train, train_ids=train_ids, max_traces=cfg.max_traces, fallback_events=train["_events"])
        if not traces:
            stop_reason = f"round {r}: every train task passes; nothing left to teach"
            break
        gate_before = cache.get(("gate", key)) or split_run("gate", gate_ids, r, paths.registry)
        cache[("gate", key)] = gate_before

        context = build_teacher_context(r, entries, traces, history)
        assert_no_leak(context, leak_terms)
        try:
            proposal = teacher.propose(context)
        except TeacherOutputError as e:
            say(f"  teacher output invalid twice: {e}")
            history.append({"round": r, "name": "(invalid output)", "outcome": "rejected", "reason": "invalid JSON/routine twice"})
            rejections += 1
            if rejections >= cfg.max_consecutive_rejections:
                stop_reason = f"{rejections} consecutive rejections"
                break
            continue
        except TeacherError as e:  # API down / auth: end the run cleanly so run.end still lands
            stop_reason = f"round {r}: teacher unavailable: {e}"
            break
        name = proposal["name"]
        say(f"  proposal: {name} — {proposal['rationale'][:100]}")

        cand = stage_candidate(proposal, paths.staging, round=r, teacher_model=teacher.model, run_id=run_id)
        log.emit("growth.proposal", routine=name, rationale=proposal["rationale"], triggerDescription=proposal["trigger_description"],
                 skillPath=rel(paths.skills / name), candidatePath=rel(cand), status="proposed",
                 edit=any(e["name"] == name for e in entries))

        try:
            findings = scan(cand, teacher=teacher)
        except TeacherError as e:
            stop_reason = f"round {r}: teacher unavailable during Warden scan: {e}"
            break
        manifest = build(cand, proposal["requested_permissions"], findings)
        (cand / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (cand / "SKILL.md").write_text(render_skill_md(proposal, round=r, teacher_model=teacher.model, manifest=manifest), encoding="utf-8")
        log.emit("warden.manifest", **{k: manifest.get(k) for k in ("skill", "read", "write", "commands", "network", "findings", "verdict")},
                 wardenImpl=warden_impl)
        say(f"  warden: {manifest['verdict']} ({len(findings)} findings)")

        if manifest["verdict"] == "dangerous":
            decision = reject_before_gate(log, name, gate_before, "warden verdict: dangerous")
        else:
            cand_registry = cand.parent / "registry.json"
            cand_entries = with_routine(entries, {"name": name, "path": rel(cand), "source": "grown"})
            save_registry(cand_registry, cand_entries)
            decision, gate_after = run_gate(routine=name, registry=str(cand_registry), before=gate_before,
                                            run_split=run_split, log=log, round=r, task_ids=gate_ids)
        say(f"  gate: {decision.gateBefore} → {decision.gateAfter} " + ("ACCEPTED" if decision.accepted else f"rejected ({decision.rejectReason})"))

        if decision.accepted:
            entry = install(proposal, cand, paths)
            entries = with_routine(entries, entry)
            save_registry(paths.registry, entries)
            cache[("gate", registry_key(entries))] = gate_after
            accepted.append(name)
            rejections = 0
            history.append({"round": r, "name": name, "outcome": "accepted"})
        else:
            rejections += 1
            history.append({"round": r, "name": name, "outcome": "rejected", "reason": _public_reason(decision.rejectReason)})

        # held-out: reporting only. Nothing below ever feeds back into `history` or the teacher context.
        hkey = ("heldout", registry_key(entries))
        if hkey in cache and not cfg.heldout_every_round:
            prev = cache[hkey]
            with log.scope(taskId=None, split="heldout"):
                log.emit("eval.heldout", passed=prev["passed"], total=prev["total"],
                         avgModelCalls=round(prev["avgModelCalls"], 3), reusedFromRound=prev["_round"])
            say(f"  round {r} heldout  unchanged harness, reusing round {prev['_round']}: {prev['passed']}/{prev['total']}")
        else:
            prev = split_run("heldout", heldout_ids, r, paths.registry)
            prev["_round"] = r
            cache[hkey] = prev
        heldout_by_round.append({"round": r, **_heldout_point(prev)})

        if rejections >= cfg.max_consecutive_rejections:
            stop_reason = f"stopped after {rejections} consecutive rejections (round {r})"
            break

    summary = {
        "heldoutByRound": [p["rate"] for p in heldout_by_round],
        "avgModelCallsByRound": [p["avgModelCalls"] for p in heldout_by_round],
        "teacherCostUsd": round(teacher.cost_usd, 4),
        "routinesAccepted": accepted,
        "heldoutDetail": heldout_by_round,
        "teacherCalls": teacher.calls,
        "roundsRun": last_round,
        "stopReason": stop_reason,
        "registry": [e["name"] for e in entries],
        "dryRun": paths.dry,
    }
    with log.scope(round=last_round, taskId=None, split=None):
        log.emit("run.end", summary=summary)
    say(f"done: {stop_reason}; accepted {accepted or 'nothing'}; held-out {summary['heldoutByRound']}; teacher ${summary['teacherCostUsd']}")
    summary["logPath"] = str(log_path)
    summary["paths"] = {"registry": str(paths.registry), "grown": str(paths.grown), "skills": str(paths.skills)}
    return summary


def _heldout_point(res: dict) -> dict:
    total = res["total"] or 1
    return {"passed": res["passed"], "total": res["total"], "rate": round(res["passed"] / total, 3),
            "avgModelCalls": round(res["avgModelCalls"], 3)}


def _public_reason(reason: str | None) -> str:
    """Rejection reason as shown to the teacher: category only, no task ids."""
    reason = reason or "rejected"
    if reason.startswith("regression"):
        return "gate: a previously passing practice-gate task regressed"
    if reason.startswith("warden"):
        return reason
    return "gate: " + reason


# --------------------------------------------------------------------------- CLI


def _ids(s: str | None) -> list[str] | None:
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m growth.grow", description=__doc__.split("\n\n")[0])
    p.add_argument("--rounds", type=int, default=4)
    p.add_argument("--fake-teacher", action="store_true", help="canned proposals, no network (implies --dry-run)")
    p.add_argument("--stub-runner", action="store_true", help="simulated run_split, no Ollama (implies --dry-run)")
    p.add_argument("--dry-run", action="store_true", help="write routines/skills/registry under .manifest/work/ instead of the repo")
    p.add_argument("--train-tasks", help="comma-separated subset of the train split")
    p.add_argument("--gate-tasks", help="comma-separated subset of the gate split")
    p.add_argument("--heldout-tasks", help="comma-separated subset of the held-out split")
    p.add_argument("--max-traces", type=int, default=6)
    p.add_argument("--round0", choices=("all", "heldout", "none"), default="all", help="which splits to (cache-)run in baseline mode as round 0")
    p.add_argument("--heldout-every-round", action="store_true", help="re-run held-out even when the harness didn't change")
    p.add_argument("--profile", choices=("core", "full", "v2"), default="core", help="task split profile from tasks/splits.json")
    p.add_argument("--max-seconds", type=int, default=240, help="per-task wall clock for every harness run")
    p.add_argument("--log", type=Path, help="event log path (default .manifest/runs/<id>-growth.jsonl)")
    a = p.parse_args(argv)

    cfg = GrowConfig(
        rounds=a.rounds, fake_teacher=a.fake_teacher, stub_runner=a.stub_runner, dry_run=a.dry_run,
        train_ids=_ids(a.train_tasks), gate_ids=_ids(a.gate_tasks), heldout_ids=_ids(a.heldout_tasks),
        max_traces=a.max_traces, round0=a.round0, heldout_every_round=a.heldout_every_round, log_path=a.log,
        profile=a.profile, max_seconds=a.max_seconds,
    )
    try:
        summary = grow(cfg)
    except (TeacherError, LeakError) as e:
        print(f"[grow] aborted: {e}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
