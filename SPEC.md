# Manifest: Spec v2 (single source of truth)

> **Manifest grows a coding-agent harness for a small local model.** A 4B model can usually *fix* a bug
> once it is looking at the right lines; it fails as an agent because of *process* (wanders, re-reads,
> never commits to an edit, never re-runs the full suite). Manifest runs the student on practice tasks,
> shows a frontier **teacher** its failures at the level of functions, and lets the teacher grow the
> missing control flow **as code** (routines). Every candidate must repair the failures it was shown,
> must not lower a separate gate set, and must earn a **Warden** permission manifest. The grown harness
> then runs **fully offline** with the 4B model, every teacher-written line inside a kernel sandbox.
>
> Taught once online. Runs offline forever. Your code never leaves your machine.

v2 replaces the hackathon spec (archived in `docs/history/`). What changed and why:

| | Hackathon (v1, 2026-10-03) | v2 (now) |
|---|---|---|
| Growth algorithm | fixed rounds, one routine per round | the paper's failure-window stream (§5): window K, repair budget R_max, edit budget L, repair threshold Q, gate + transactional rollback |
| Teacher sees | ≤6 failed traces (routine/tool/student calls) | the window's traces **with a function-level execution graph** inside routines (`fn.call`/`fn.return`) + offline diagnostics |
| Teacher may change | exactly one routine | up to L functions across routines, inside the trace-scoped set; no deletions |
| Gate rule | gate ↑ (or = with −20 % calls) and no per-task regression | paper rule: ≥ Q window repairs **and** SR_gate(candidate) ≥ SR_gate(checkpoint); per-task regressions logged |
| Budget | 240 s wall clock (binding) | 12 steps / 24 student calls (binding, same for every harness), 1800 s wall clock only as a safety cap |
| Held-out | every round | once per finished harness (h0, h\*), never during growth |
| Sandbox | macOS `sandbox-exec`, not actually used during eval | Linux `bwrap` (and macOS), used for every grown routine (`run` **and** `applies`) and every tool subprocess |
| Evidence | one run, 3/3/3 tasks | full suite, per-task records, task-level bootstrap CIs, paired comparisons, ablations |

---

## 0. Ground rules

- **Never hand-write grown routines.** `harnesses/<run>/routines/` and `routines/grown/` come only from the
  teacher, with provenance in the growth log (`growth.proposal`). The seed routines stay minimal.
- **The teacher never sees held-out material**: no ids, no traces, no outcomes, no task contents, and not
  the held-out-only domain. Enforced by `assert_no_leak` on every teacher context (unit-tested).
- The teacher only sees **synthetic generated tasks**, never a user's repo.
- **The harness never grades itself.** The runner re-runs the real suite and fails any task whose test-side
  files changed (§3.4).
- Grown routines may not encode task ids, domain names, module names or expected answers (§5.4 lint).
- Every number in `RESULTS.md` is recomputed from committed event logs by a script. Nothing hand-entered.
- Cite *"Grow the Harness, Not the Context"* (arXiv 2609.26760). Our additions: coding domain with verified
  bug shapes, routines exported as Agent Skills, Warden in the gate and at run time, fully offline deployment.
- Commit at every checkpoint; never commit `.env`.

## 1. Models and host

| Role | Model | Access | Settings |
|---|---|---|---|
| Student | Qwen3.5-4B `qwen3.5:4b` (Q4_K_M) | Ollama ≥ 0.35, `http://localhost:11434` | `temperature 0`, `think=False`, `num_ctx 16384`, `num_predict 768`, `num_thread` = `STUDENT_NUM_THREAD` (4 on the VM) |
| Teacher | DeepSeek V4.1 Flash, API id `deepseek-flash` | OpenAI-compatible, `https://api.deepseek.com`, key `DEEPSEEK_API_KEY` in `.env` | `temperature 0`, JSON mode, validated + one retry |

Reference host for v2 numbers: `skywalker`, GCP VM, 4 vCPU AMD EPYC 7B12 (2 cores × 2 threads), 8 GB RAM,
**CPU only**. Measured: ~20–23 tok/s prompt eval, ~5–8 tok/s generation, so one student turn is 50–90 s
and a 12-step tool-calling task is 15–20 min. Ollama reuses the KV prefix of the previous request (single
slot), so an appended conversation turn costs only its new tokens while a fresh 3k-token prompt costs
~2.5 min. Every `run.start` records `host` (CPU, RAM, Ollama version, model digest, options, code hash).

**Teacher spend policy** (`harness/teacher.py`, `harness/budget.py`):
- Prices are DeepSeek's published per-1M rates with the peak/off-peak schedule
  (peak = 01:00–04:00 and 06:00–10:00 UTC, Mon–Fri; off-peak is half price). Defaults: off-peak $0.15 in /
  $0.003 cached / $0.60 out; peak double. Overridable from `.env`.
- Every teacher call is appended to `.manifest/teacher-ledger.jsonl` (ts, purpose, tokens, cost, run id).
- Hard caps: `TEACHER_BUDGET_USD` (all-time, default 2.00) and `--teacher-budget` per run (default 0.75).
  A call that would start above the cap raises `TeacherBudgetExceeded` and the growth run checkpoints.
- `--teacher-hours offpeak` (default for long runs) waits for off-peak before each teacher call.

## 2. Repo layout

```
SPEC.md  CONTRACT.md  CLAUDE.md  README.md  RESULTS.md  ROADMAP.md
tasks/        gen.py, mutations.py, templates/<domain>/, generated/<task-id>/, splits.json, index.json, labels.py
harness/      student.py, teacher.py, budget.py, tools.py, loop.py (baseline), controller.py, state.py,
              fntrace.py (function-level trace), env.py (env + host provenance), log.py, run.py
routines/     seed/{start,ask-student}   grown/ + registry.json (the hackathon harness, kept as-is)
harnesses/    <run-id>/registry.json + routines/<name>/{routine.py,manifest.json,SKILL.md,proposal.json}
              one directory per v2 growth run: every accepted harness version h_t, final h*
growth/       stream.py (v2 growth, paper Alg. 1), grow.py (v1 rounds + shared helpers), gate.py,
              traces.py, validate.py (edit budget / scope / specificity), eval.py (runner), report.py, stats.py
warden/       scan.py, manifest.py, sandbox.py (bwrap | sandbox-exec), _child.py, cli.py, card.py
skills/       exported Agent Skills (grown routines that were promoted) + skills/warden/
gui/          Vite + React viewer and launcher over .manifest/runs/*.jsonl
demo/         rigged third-party skill, fakehome (fake ~/.ssh), sink
docs/history/ hackathon SPEC / CONTRACT / SPECLIST / CLAUDE.md
.manifest/    runs/*.jsonl (committed evidence), cache/ (round-0 per-task cache), growth/<run>/ (checkpoints)
```

## 3. Tasks and evaluation protocol

### 3.1 Suite
Generated, deterministic (seed 1337) multi-module Python services; each task = one package + pytest suite +
exactly one injected root-cause bug + `TASK.md` ("The test suite is failing. Make it pass without editing
tests."). Domains: `ledgerly`, `stockroom`, `slotbook`, `ratekeeper`, `csvflow` (held-out only). Bug shapes
(mechanically verified by `tasks.gen`): deep call chain, one root / many failures, regression trap,
misleading surface. Root-cause metadata lives only in `tasks/index.json`.

### 3.2 Splits
`tasks/splits.json` profiles: `full` (train 12 / gate 6 / held-out 8 incl. 2 novel-domain), `core`
(3/3/3), `demo`. **ROADMAP:** grow the suite (more verified mutations per template, one more held-out-only
domain) so held-out CIs tighten; new tasks are appended to splits, never reshuffled, so earlier per-task
results stay valid.

### 3.3 Budget (identical for every harness)
- **12 steps** per task (baseline: model turns; controller: routine runs) and **24 student calls**.
- **1800 s** wall clock per task as a safety cap only. A task that hits it is labelled `budget` if the
  model was still answering; such runs are reported separately, never silently counted as process failures.
- Student temperature 0. Determinism is checked, not assumed (§3.6).

### 3.4 Judging
`growth/eval.py` copies the task to `.manifest/work/<run>/<split>/<task>/`, sets `HOME=demo/fakehome`, runs
the harness, then re-runs the full suite itself. Pass ⇔ every original test passes **and** no test-side file
(`tests/**`, conftest, pytest config, `.pth`, `sitecustomize`) changed or appeared.

### 3.5 Metrics (per task, from the event log)
pass; student calls; prompt tokens (and Ollama's prefix-reuse is visible as low `promptTokens`-per-ms);
output tokens; wall time; steps; routine calls; stop reason; failure label (`process|knowledge|format|budget`,
`tasks/labels.py`); Warden blocks. Teacher: calls, tokens (cache hit/miss), USD.

### 3.6 Statistics (`growth/stats.py`)
- Success rate with a **task-level bootstrap** 95 % CI (10 000 resamples), as in the paper.
- Harness vs harness on the same tasks: paired difference with paired bootstrap CI, plus the discordant
  counts (b = only A passes, c = only B passes) and an exact McNemar p-value.
- Efficiency (calls, tokens, seconds): mean ± bootstrap CI, paired where applicable.
- Determinism: a repeat of a subset reports per-task agreement; if runs disagree, report R runs and the
  mean over runs, as the paper does (R = 3).

## 4. Harness

- **Baseline** (`--mode baseline`): plain tool-calling loop, tools `list_files`, `read_file`, `run_tests`,
  `edit_file`, `bash`. The student decides everything. This is the paper's *Tool-Calling* baseline.
- **Controller** (`--mode manifest`): a code loop over the registry; first routine whose `applies(state)` is
  true runs; repeat until `state.done` or the budget. Seeds: `start` (load TASK.md, list files) and
  `ask-student` (fallback: one tool-calling turn, i.e. baseline behaviour). **h0 = seeds only** (the paper's
  strategy-free scaffold).
- Routine API: `NAME`, `applies(state) -> bool`, `run(state, tools, student) -> state`. Student calls:
  `student.ask(purpose, prompt, schema)` (validated, re-asked once), fixed formats `diagnose`, `patch`.
- **Execution** (`warden.sandbox.make_executor`, default `auto`): seed routines run in-process; every other
  routine (grown, candidates) runs `run()` **and** `applies()` in Warden's kernel sandbox; tool and student
  calls are proxied to the parent so `Tools` (manifest-checked) and `EventLog` stay authoritative.
- **Function-level trace** (`harness/fntrace.py`): every function defined in a routine module is wrapped;
  calls emit `fn.call {routine, fn, depth, args}` and `fn.return {routine, fn, depth, ret|exc, ms}`, so a
  task's events form the execution graph routine → functions → tool/student calls.
- Tool subprocesses (pytest, the student's `bash`) run in bwrap: no network, no `$HOME`, `tests/` read-only.

## 5. Growth (paper Algorithm 1, mapped to routines): `python -m growth.stream`

### 5.1 Objects
- Harness h_t = ordered registry + routine sources. "Functions" = top-level functions of routine modules;
  the registry order + every routine's `applies()` play the role of the paper's `main` dispatcher.
- Trace τ_i = task events: `routine.call`, `fn.call/return`, `tool.call`, `model.call`, `warden.block`, plus
  the outcome. ℱ(τ_i) = routines that ran in τ_i and the functions called inside them.
- Diagnostics E_i (offline, train only, no root cause): final judge result (still-failing tests + first
  error line), stop reason, action statistics (reads, distinct files, edits ok/failed, test runs, full
  re-runs after the last edit, repeated identical calls), the attempt count a_i.

### 5.2 Loop
```
stream ← train tasks (fixed order); W ← ∅; h ← h0; h_gate ← h0; SR_gate ← SR_G(h0)
while stream not exhausted or W ≠ ∅:
    while |W| < K and stream not exhausted: run h on next task; failures join W with a=0
    if W = ∅: break
    checkpoint(h, cursor, W, counters)                          # resumable; rollback target
    cand ← teacher(h, traces+diagnostics of W, history)         # §5.3
    if invalid (schema / edit budget / scope / deletion / lint) or Warden "dangerous":
        reject; attempts(W) += 1; retire a ≥ R_max; continue
    re-run cand on W → P (solved), U
    if |P| < Q: reject (insufficient repair); attempts += 1; retire; continue
    if SR_G(cand) < SR_gate: reject (gate regression) → rollback; attempts += 1; retire; continue
    accept: h ← cand; h_gate ← cand; SR_gate ← SR_G(cand); W ← U with fresh traces, a+1, retire a ≥ R_max
h* ← h; evaluate h* once on held-out
```
Rejections never touch `harnesses/<run>/` beyond the candidate's staging dir; acceptance writes version
`h<t>/` and moves `current`. Stop early on `--max-steps`, teacher budget, or `--max-hours`; all resumable
from `.manifest/growth/<run>/checkpoint.json`.

### 5.3 Teacher input and output
Input Z_t = (current harness source with per-routine scope marks, window traces rendered as a nested
execution graph, diagnostics, history of earlier steps (names, outcomes, categories only), routine API).
Output JSON:
```json
{"rationale": str,
 "changes": [{"name": str, "trigger_description": str, "routine_py": str, "skill_md": str,
              "requested_permissions": {"read": [..], "write": [..], "commands": [..], "network": false}}],
 "order": [str]}      // optional new order of grown routines (seeds stay first/last)
```

### 5.4 Constraints (validated in `growth/validate.py` before anything runs)
- Edit budget **d_fun ≤ L**: added or modified top-level functions summed over all changed routines.
- **Scope**: a routine's body may change only if it ran in some window trace; trigger-only changes
  (`applies`, `NAME`, constants) are always allowed (they are the dispatcher). New routines are allowed.
- **No deletions**: existing routines stay in the registry; existing top-level functions stay defined.
- ≤ 150 lines per routine; stdlib + pydantic; the routine API; seeds are immutable.
- **Specificity lint**: no task ids, domain names, template module names (e.g. `money`, `bucket`), or
  literal expected answers. Violations reject the candidate (logged as `validate`).
- Warden: static scan + teacher deobfuscation summary → manifest; `dangerous` rejects.

### 5.5 Hyperparameters (defaults; paper values in brackets)
K = 4 [8 / 4], R_max = 3 [5], Q = 1 [repair threshold], L = 10 [10], candidates/step = 1 [1],
budget per task as §3.3 [50 calls, 900–1800 s]. Train stream = `full` train (12), gate = `full` gate (6).

### 5.6 Ablations (`--ablate`)
`no-gate` (accept on repairs alone), `window-1` (K = 1), `no-fn-trace` (traces without `fn.*` events and
no scope restriction: whole-program edits), each a full growth run evaluated once on held-out.

## 6. Warden
- **Static scan** (`warden/scan.py`): network imports/calls, subprocess/os.system, eval/exec/decode-then-
  exec, paths outside the task dir, env/secret reads, hidden instructions in SKILL.md; plus a teacher pass
  that deobfuscates and summarises the code.
- **Manifest** (`warden/manifest.py`): `{skill, read, write, commands, network, findings, verdict}`;
  grown default read `**`, write `src/**`, commands `python -m pytest`, network false.
- **Runtime** (`warden/sandbox.py`): Linux bubblewrap (namespaces; only the interpreter, venv, harness code,
  routine dir and manifest globs are mounted; `tests/` read-only; fake home with masked `.ssh`; no network)
  or macOS `sandbox-exec` (Seatbelt profile). An audit hook in the child logs `warden.block` and raises
  PermissionError. No kernel sandbox → audit-hook-only fallback, reported as such.
- CLI: `manifest warden audit <dir>`, `manifest skill add <dir> [--force-run]`. Agent Skill `skills/warden/`.

## 7. Event log
Schema in `CONTRACT.md`. One JSONL per invocation in `.manifest/runs/`; a growth run is one file.
v2 adds `fn.call`, `fn.return`, `growth.window`, `growth.repair`, `growth.step`, `growth.checkpoint`, and
`run.start.host`. Consumers ignore unknown fields and types.

## 8. GUI
`gui/`: replay/live-tail of event logs, task board, session view, growth timeline with Warden cards,
results. Launches only allow-listed CLI invocations. Must keep working fully offline.

## 9. Experiments (each one log, each in RESULTS.md)
| id | what | split(s) | needs teacher |
|---|---|---|---|
| E1 | baseline tool-calling (student only) | full: train, gate, held-out | no |
| E2 | h0 seed controller | full held-out (+ train/gate inside growth) | no |
| E3 | hackathon harness (`triage-fix`) | full held-out | no |
| E4 | v2 growth run → h\* | train stream + gate | yes |
| E5 | h\* evaluated once | full held-out | no |
| E6 | ablations (§5.6) | as E4/E5 | yes |
| E7 | budget sensitivity: baseline at 24 steps on a subset | held-out | no |
| E8 | Warden: selftest, rigged-skill force-run, blocks during E4/E5 | n/a | no |
