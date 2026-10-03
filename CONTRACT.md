# CONTRACT.md

> Frozen interfaces between worktrees. Part 1 is SPEC section 7 verbatim. Part 2 pins the Python seams so A–E can build in parallel. Change only via the integrator (the human).

# Part 1 — Event log


One JSON object per line. Every event has `{ts, type, round, taskId, split}` (`taskId`/`split` may be null).

| type | extra fields |
|---|---|
| `run.start` | `mode, student, teacher, online: bool` |
| `task.start` | `domain, bugShape` |
| `task.end` | `pass, steps, modelCalls, routineCalls, ms` |
| `routine.call` | `routine, summary, ms` |
| `model.call` | `model, role: "student"/"teacher", purpose, promptTokens, outTokens, ms, cacheHitTokens?` |
| `tool.call` | `tool, args, ok, summary` |
| `growth.proposal` | `routine, rationale, triggerDescription, skillPath` |
| `warden.manifest` | `skill, read[], write[], commands[], network, findings[], verdict` |
| `warden.block` | `skill, attempted, reason` |
| `gate.result` | `routine, accepted, gateBefore, gateAfter, regressions[], modelCallsBefore, modelCallsAfter` |
| `eval.heldout` | `passed, total, avgModelCalls` |
| `run.end` | `summary` |


**Event-log rules (integrator clarifications):**
- `ts` = ISO-8601 UTC with milliseconds, e.g. `2026-10-03T07:31:02.123Z`. `round` = int, `0` = baseline. `split` ∈ `"train" | "gate" | "heldout" | null`.
- Field names are camelCase exactly as above. Extra fields are allowed; consumers ignore unknown fields. Never rename/remove listed fields.
- One file per invocation: `.manifest/runs/<YYYYMMDD-HHMMSS>-<label>.jsonl` (e.g. `20261003-134500-growth.jsonl`). A full growth run (all rounds) is ONE file so the GUI can replay it. Append + flush per line (the GUI tails it live).
- Write events only through `harness/log.py` (`EventLog`), already on `main`.
- Optional extras we agreed on: `task.start.mode`, `routine.call.source` (`"seed"|"grown"`), `model.call.costUsd` (teacher), `gate.result.rejectReason`, `growth.proposal.status` (`"proposed"`), `run.end.summary` = `{heldoutByRound: [..], avgModelCallsByRound: [..], teacherCostUsd, routinesAccepted: [..]}`.

# Part 2 — Python seams

## 2.1 Task on disk (owner A)
```
tasks/generated/<task-id>/          # the ONLY thing the student/harness ever sees
  TASK.md                           # "The test suite is failing. Make it pass without editing tests."
  src/<pkg>/*.py   tests/test_*.py  conftest.py (adds src/ to sys.path)
tasks/splits.json                   # {"seed":1337,"train":[ids],"gate":[ids],"heldout":[ids],"novelDomain":"<domain>"}
tasks/index.json                    # {id: {domain, bugShape, mutation, rootCause:{file,function,line}, failingTests:[..]}}
```
- Task id: `<domain>-<nn>` (e.g. `ledgerly-03`). Root-cause metadata lives ONLY in `tasks/index.json`, never inside the task dir.
- Tests run with: `python -m pytest -q -p no:cacheprovider` from the task dir. Pristine tasks must fail; the reference fix must pass.

## 2.2 Runner (owner A) — `growth/eval.py`
```python
run_split(split: str, *, mode: str, round: int, log: EventLog,
          registry: str | None = None, task_ids: list[str] | None = None) -> SplitResult
# SplitResult = {split, passed, total, avgModelCalls, results: [TaskOutcome]}
# TaskOutcome = {taskId, pass, steps, modelCalls, routineCalls, ms, events: [dict]}
```
- Copies each task to `.manifest/work/<run-id>/<task-id>/` (pristine dir is never touched), sets `HOME=demo/fakehome`, calls `harness.run.run_task(...)`, then judges pass **itself** by re-running the full suite in the workdir AND checking `tests/` is byte-identical to pristine.
- Emits `task.start` (before) and `task.end` (after). Emits `eval.heldout` when `split == "heldout"`.
- CLI: `python -m growth.eval --split train --mode baseline --round 0 [--tasks a,b] [--registry routines/registry.json]`.
- Round-0 baseline results are cached in `.manifest/cache/round0-<split>.json`; never recomputed unless `--force`.

## 2.3 Harness entry (owner B) — `harness/run.py`
```python
run_task(workdir: Path, *, mode: Literal["baseline","manifest"], log: EventLog,
         registry: str | None = None, max_steps: int = 12, max_seconds: int = 120,
         executor: "Executor | None" = None) -> dict   # {steps, modelCalls, routineCalls, selfReportedDone}
```
- Emits `routine.call`, `model.call` (student), `tool.call`, `warden.block`. Does NOT emit task.start/end.
- `harness/tools.py`: `Tools(workdir, manifest: dict | None, log)` with `list_files()`, `read_file(path, start=None, end=None)`, `run_tests(selector=None) -> {passed, failed, output, failures:[{test, error, frames:[{file,line,function}]}]}`, `edit_file(path, search, replace)`, `bash(cmd)`. Tool layer enforces the manifest (paths + command prefixes) and logs `warden.block`.
- `harness/student.py`: `Student(log)` → `.chat(messages, tools)` (baseline) and `.ask(purpose, prompt, schema: type[BaseModel]) -> dict` (validated, re-asked once). Settings per SPEC §1.
- `harness/state.py`: `State` — pydantic model, JSON-serialisable (routines may run out-of-process).

## 2.4 Routines + registry (owner B; C appends)
```python
# routines/<seed|grown>/<name>/routine.py
NAME = "trace-to-source"
def applies(state) -> bool: ...
def run(state, tools, student) -> state: ...
```
- `routines/registry.json` = ordered list `[{"name","path","source":"seed|grown"}]`. Seeds: `start` first, `ask-student` (fallback) **always last**. Grown routines are inserted immediately before `ask-student`.
- Each grown routine dir also holds `manifest.json` (Warden) and `SKILL.md`.
- `Executor` protocol (B defines in-process default; D provides sandboxed): `executor.run(routine_dir: Path, state: State, tools, student, manifest: dict) -> State`.

## 2.5 Teacher + growth (owner C)
- `harness/teacher.py`: `Teacher(log)` → `.propose(context: dict) -> dict` with keys `{name, rationale, trigger_description, routine_py, skill_md, requested_permissions}`; `.summarize_code(src) -> list[str]` (used by Warden). OpenAI client, base `TEACHER_BASE_URL`, model `TEACHER_MODEL`, temp 0, JSON validated, retry once. Emits `model.call` with `role:"teacher"`, `costUsd`.
- Teacher context is built ONLY from train-split events. A unit test asserts no held-out task id/content appears in any teacher prompt.

## 2.6 Warden (owner D)
```python
warden.scan.scan(path: Path, teacher=None) -> list[dict]            # findings [{rule, severity, file, line, detail}]
warden.manifest.build(skill_dir: Path, requested: dict | None, findings: list) -> dict
#   -> {skill, read, write, commands, network, findings, verdict: "ok"|"review"|"dangerous"}
warden.sandbox.SandboxExecutor(log)                                  # implements Executor; macOS sandbox-exec
```
- Default grown manifest: read `**` (task dir), write `src/**`, commands `["python -m pytest"]`, network `false`. Student calls to `localhost:11434` are the only allowed socket.
- CLI (`manifest` entry point = `warden/cli.py:main`): `manifest warden audit <dir>`, `manifest skill add <dir> [--force-run]`.
