# Manifest: Build Spec (single source of truth)

> **Manifest is a coding-agent harness that grows itself.** A 4B model on a laptop fails at agent work because of *process* (loops, bad tool calls, never re-running tests), not intelligence. Manifest watches it fail on practice tasks; an open frontier model (DeepSeek V4.1 Flash) writes the missing control routines as **code**; each routine must pass a gate on unseen tasks and earn a **permission manifest** from **Warden** before it is kept. After growth, the 4B model + grown harness runs **fully offline** on your real code.
>
> **Tagline:** Taught once online. Runs offline forever. Your code never leaves your laptop.

Every agent working on this repo: read this whole file first. Do not change the **Contracts** section without the integrator (the human).

---

## 0. Ground rules

- License: MIT. Public GitHub repo.
- **Never hand-write grown routines.** The seed harness is deliberately minimal. Every routine in `routines/grown/` must come from the teacher and be logged (`growth.proposal`). Hand-writing them would fake the result.
- Teacher never sees anything from the **held-out** split (no outcomes, no traces, no task contents).
- Teacher only ever sees **synthetic generated tasks**, never a user's real repo.
- Cite the paper in the README: *"Grow the Harness, Not the Context" (arXiv 2609.26760)*. Our additions: coding domain, routines exported as Agent Skills, Warden in the gate + at runtime, fully offline deployment.
- Disclose any starters/templates in README.
- Commit every ~30 minutes with clear messages.

## 1. Models

| Role | Model | Access | Settings |
|---|---|---|---|
| **Student** | Qwen3.5-4B (`qwen3.5:4b`) | Ollama, local, `http://localhost:11434` | `temperature 0`, `num_ctx 16384` (8 GB RAM), thinking **off** (`think=False`), max output 768 tokens |
| **Teacher** | DeepSeek V4.1 Flash (MIT open weights) | OpenAI-compatible API, base `https://api.deepseek.com`, key `DEEPSEEK_API_KEY`, model id from env `TEACHER_MODEL` (check the exact id in the DeepSeek console) | `temperature 0`; validate every JSON response, retry once on invalid |

Same student model as the paper's small-model setting. That's deliberate: it lets us compare against published numbers.

## 2. Repo layout

```
manifest/
  SPEC.md  README.md  LICENSE  CONTRACT.md (= section 7 copied)
  tasks/        gen.py, templates/, splits.json, generated/<task-id>/
  harness/      loop.py (baseline tool-calling), controller.py (routine engine),
                tools.py, student.py, teacher.py, log.py
  routines/     seed/ (minimal, hand-written, tiny), grown/ (teacher-written only)
  growth/       grow.py (rounds), gate.py, eval.py
  warden/       scan.py, manifest.py, sandbox.py (macOS sandbox-exec profiles), cli.py
  skills/       exported Agent Skills (one per accepted routine) + skills/warden/
  gui/          Vite + React viewer over .manifest/runs/*.jsonl
  demo/         thirdparty-skills/ (rigged, harmless), fakehome/ (fake ~/.ssh), sink.py
  .manifest/runs/   event logs (JSONL)
  .github/workflows/skills.yml   (skills-ref validate skills/*)
```

Python 3.11+ for everything except `gui/`. Deps: `ollama`, `openai`, `pytest`, `pydantic`.

## 3. Task suite ("serious, not toy")

Generated, deterministic (fixed seed), **multi-module Python packages** that look like real small services. Every task = one package + a pytest suite + exactly one injected root-cause bug + `TASK.md` ("The test suite is failing. Make it pass without editing tests.").

**Domains** (each a package with 5–8 modules, 20–40 tests):
1. `ledgerly`: invoices, line items, tax, discounts, currency rounding
2. `stockroom`: inventory, reservations, reorder thresholds
3. `slotbook`: scheduling, time ranges, overlap detection, time zones
4. `ratekeeper`: token-bucket rate limiter, windows, quotas
5. `csvflow`: CSV ingest, schema validation, transforms, aggregation

**Bug shapes**: what makes it serious. The fix is always small *once found*; finding it takes process:
- **Deep call chain**: the failing test is in `test_invoice.py`, but the bug is 2–3 calls down in `money.py` (must follow the traceback to the innermost *repo* frame).
- **One root cause, many failures**: 3–6 tests fail from one bug in a shared util.
- **Regression trap**: the obvious local fix makes another test fail (must re-run the *full* suite and roll back).
- **Misleading surface**: the error message points at a caller; the defect is in the callee.
- Mutation operators: wrong comparison, off-by-one in range or slice, missing return, swapped args, wrong rounding mode, wrong default, inverted condition.

**Splits**: 26 tasks total: `train` 12, `gate` 6, `heldout` 8. Held-out includes 2 tasks from a domain **not present** in train/gate (generalization). Stored in `tasks/splits.json`.

**Run limits**: max 12 student steps per task; wall clock 120 s per task.

## 4. Harness

### 4.1 Baseline mode (`--mode baseline`): round 0
Plain tool-calling loop (what Pi or DeepSeek Harness would do with a small model). Tools: `list_files`, `read_file(path, start, end)`, `run_tests(selector?)`, `edit_file(path, search, replace)`, `bash(cmd)` (sandboxed to the task dir). The student decides everything.

### 4.2 Controller mode (`--mode manifest`)
A **code** controller drives a state object through **routines**. The student is called only for semantic steps.

```python
# routines/<name>/routine.py
NAME = "trace-to-source"
def applies(state) -> bool: ...          # trigger condition, written in code
def run(state, tools, student) -> state:  # deterministic code; may call student.ask(purpose, prompt, schema)
```
- Controller loop: pick the first routine whose `applies(state)` is true (registry order), run it, repeat until `state.done` or limits hit.
- Seed routines (hand-written, tiny): `start` (load TASK.md, list files), `ask-student` (fallback: give the student the state and let it pick a tool, i.e. baseline behaviour). That's all.
- Student semantic calls use **fixed formats** (validated): `diagnose` → `{file, function, hypothesis}`; `patch` → a single search/replace block. Invalid output is re-asked once with the validation error.
- Every routine runs through Warden's runtime enforcement (section 6.3).

### 4.3 State (minimum)
`task_dir, test_output, failures[{test, error, frames[]}], suspect{file, line, function}, context_snippet, patches[], last_full_run{passed, failed}, done, steps, model_calls`

## 5. Growth loop (`growth/grow.py`)

Per round `r = 1..4`:
1. Run current harness on **train**; keep up to 6 failed traces (bounded window).
2. **Teacher prompt** includes: this spec's routine API, current controller registry + routine source, the failed traces (function-level: which routine ran, inputs/outputs, student calls), and the instruction: *"Propose exactly ONE change: a new routine (≤150 lines) or an edit to one existing routine's code or trigger. Move recurring control decisions into code; leave only semantic judgement to the student."* Output JSON: `{name, rationale, trigger_description, routine_py, skill_md, requested_permissions}`.
3. **Warden**: static scan + generate the permission manifest (section 6). Reject if dangerous.
4. **Gate**: run on the **gate** split with the candidate. Accept iff gate passes ↑ (or equal with model calls ↓ ≥ 20%) **and** no previously passing gate task regresses. Log `gate.result`.
5. If accepted: copy to `routines/grown/`, export to `skills/<name>/` (spec-compliant SKILL.md + `scripts/routine.py`), append to registry.
6. Run **held-out** for reporting only → `eval.heldout`. Nothing from this goes to the teacher.

Stop early if 2 consecutive rejections. Expected teacher cost: well under $0.50 total.

**8 GB RAM note**: run tasks sequentially; nothing else heavy open. The round-0 baseline is the slowest run. Cache round-0 results; never recompute them.

## 6. Warden (permission manifests + enforcement)

### 6.1 Static scan (`warden/scan.py`)
Rules (regex/AST): network imports/calls (`socket`, `urllib`, `requests`, `http`, `curl`, `wget`), `subprocess` with shell strings, `eval`/`exec`/base64-decode-then-exec, paths outside the task dir (`~`, `/Users`, `..`), env reads (`os.environ`, `.env`). Plus a teacher pass: deobfuscate and summarize what the code actually does → `findings[]`.

### 6.2 Manifest (`warden/manifest.py`)
`{skill, read: [globs], write: [globs], commands: [prefixes], network: false|true, findings: [], verdict}`. Default for grown routines: read `**` in the task dir, write `src/**` only (never `tests/**`), commands `python -m pytest`, network **false**.

### 6.3 Runtime enforcement (`warden/sandbox.py`)
- Every routine and every skill script executes in a **subprocess under macOS `sandbox-exec`** with a profile generated from its manifest: deny network unless allowed; file reads/writes limited to the allowed globs plus the system paths needed for Python.
- The tool layer also checks paths and commands before executing (defense in depth; logs `warden.block`).
- `HOME` is set to `demo/fakehome/` for all runs (contains a fake `~/.ssh/id_ed25519`).
- **Test this in the first 20 minutes.** If `sandbox-exec` fights you, fall back to tool-layer enforcement plus running the subprocess with `HOME=fakehome`, and say so honestly in the README.

### 6.4 CLI
`manifest warden audit <skill-dir>` → bordered permission card + verdict. `manifest skill add <dir>` → audit, then install with manifest.

### 6.5 The `warden` Agent Skill (`skills/warden/`)
Spec-compliant (agentskills.io): `name: warden`, a description of when to use it ("before installing or running any third-party agent skill"), `scripts/audit.py` that runs the static scan + manifest generation. Works in Claude Code, Codex, etc.

## 7. Contracts: event log (`.manifest/runs/<run-id>.jsonl`)

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

## 8. GUI (`gui/`): a viewer, never a controller

Vite + React. Reads `.manifest/runs/*.jsonl`. **Replay** mode (speed 1×–20×, scrub by round) and **Live** mode (tails the newest file).

Layout:
- **Top bar**: Student `qwen3.5:4b · local` | Teacher `DeepSeek V4.1 Flash` | big **ONLINE / OFFLINE** badge | round indicator.
- **Left: Task board**: grid of train / gate / held-out cells, red → green per round; held-out visually distinct ("never seen by the teacher").
- **Center: Live trace**: rows for each event; **routine rows (code)** and **student rows (model)** look clearly different, so judges see code doing the control. Expand a row for details.
- **Right: Growth timeline**: per round: proposed routine name + rationale → Warden permission card (read/write/commands/network chips, findings) → gate result (before → after, regressions) → accepted/rejected stamp.
- **Bottom: Results**: held-out pass rate by round (line), avg model calls per task by round, total teacher cost.

Build first against a realistic fake run file (3 rounds, one Warden rejection, one block). Use Impeccable (`/impeccable critique`, `/impeccable polish`). It must look deliberate, not like a default dashboard.

## 9. Demo (target 3 minutes; same script for the 2:30 scoring round and the 4:15 pitch)

1. **Hook (15 s):** "Small models can think. They can't juggle. Manifest grows the juggling for them, then gets out of the way."
2. **Round 0 (30 s, replay):** held-out board mostly red. Expand one failing `ledgerly` trace: the student ran the tests, opened `invoice.py` (wrong file), edited it, broke two other tests, never re-ran the full suite, and looped until it hit the step limit.
3. **Growth (60 s, replay at speed):** round by round, the teacher proposes a routine (expected kinds: following the traceback to the innermost repo frame, verify-and-rollback, patch repair; whatever it actually produced). Each shows a Warden card (no network, can't write `tests/`) and the gate going up with no regressions. Point at a **rejected** proposal, if one happened.
4. **Warden moment (20 s):** `manifest skill add demo/thirdparty-skills/quick-fix-pro`, a "marketplace" skill. Card says DANGEROUS (reads `~/.ssh`, network). Force-run it anyway → `warden.block` from the sandbox. The sink receives nothing.
5. **Wi-Fi off (45 s, LIVE):** turn Wi-Fi off; badge flips to OFFLINE. Run a **held-out** `ledgerly` task (deep call chain + regression trap). Live trace: code routines run the tests, follow the traceback to `money.py`, and the student makes only ~2 calls (diagnose, patch). Verify-and-rollback runs the full suite → green.
6. **Numbers (20 s):** held-out pass rate round 0 → final; model calls per task before → after; total teacher cost; N routines exported as Agent Skills, validated in CI ("use them in Claude Code today").
7. **Close (10 s):** "Taught once online. Runs offline forever. Your code never leaves your laptop."

Backup: record the full demo as a video by 2:15.

## 10. Build order (cut from the bottom)

1. Task generator + test runner + splits
2. Baseline loop + student + event log (round 0)
3. Controller + seed routines
4. Growth loop + teacher + gate + held-out eval
5. Warden runtime enforcement (sandbox)
6. GUI (parallel from the start against fake data)
7. Warden static scan + teacher deobfuscation
8. Skills export + `warden` skill + CI validation
9. Third-party rigged-skill demo

## 11. Worktrees

| WT | Owns | First deliverable |
|---|---|---|
| **A: tasks** | `tasks/`, `growth/eval.py` runner | 26 tasks + splits + a script that runs any harness over a split and logs events |
| **B: harness** | `harness/`, `routines/seed/` | Baseline loop on Ollama; controller engine; event log per section 7 |
| **C: grow** | `growth/grow.py`, `gate.py`, `teacher.py` | One full round end to end on 3 train + 2 gate tasks |
| **D: warden** | `warden/`, `skills/warden/`, `demo/` | `sandbox-exec` profile proven to block `~/.ssh` read + network; permission card CLI |
| **E: gui** | `gui/` | Viewer against fake run file; then point at real runs |

Integrator rule: merge A+B first (round 0 is the earliest real result), then C, then D. E merges whenever.

## 12. Timeline (code freeze 4:00 PM)

| Time | Milestone |
|---|---|
| 12:25 | Repo + SPEC + LICENSE pushed; worktrees A, B, D, E start; `ollama pull qwen3.5:4b` |
| 12:55 | **Checkpoint**: round-0 baseline on 5 train tasks with failure labels (process vs knowledge). If mostly knowledge failures, simplify bugs or show the failing line. C starts. |
| 1:00–1:45 | Lunch; agents keep building (C, D, E) |
| 1:45 | **Start the real growth run** (all rounds, logged); it runs while you polish |
| 2:15 | Record the backup demo video |
| 2:30 | Scoring round: GUI replay + live offline task |
| 3:00–3:45 | Numbers into README, skills export + CI green, Impeccable polish, final commit |
| 3:50 | Submit on the MLH portal (tick every eligible challenge) |
