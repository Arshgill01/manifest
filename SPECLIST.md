# SPECLIST — build checklist (tick as you go)

Build order (SPEC §10) and merge order: **A+B → C → D**, E anytime. Checkpoint 12:55 = round-0 baseline on 5 train tasks with failure labels.

## Integrator (main) — done at setup
- [x] Repo skeleton, MIT LICENSE, SPEC.md, CONTRACT.md, CLAUDE.md, pyproject (uv), `.env.example`
- [x] `harness/log.py` EventLog (contract writer, shared by all tracks)
- [x] Worktrees `wt/a-tasks … wt/e-gui`; `qwen3.5:4b` pulled; Ollama 0.35 running
- [ ] `.env` with `DEEPSEEK_API_KEY` + exact `TEACHER_MODEL` id (human)
- [ ] Merge A+B → run round-0 baseline → checkpoint labels (process vs knowledge)
- [ ] Start real growth run by 1:45 (one JSONL, all rounds)
- [ ] Backup demo video 2:15 · README numbers 3:00 · MLH submit 3:50

## A — tasks (`tasks/`, `growth/eval.py`)
- [x] Deterministic generator `tasks/gen.py` (seed 1337) → `tasks/generated/<id>/`, `splits.json`, `index.json` (root cause outside task dirs)
- [x] 5 domains as real multi-module packages (5–8 modules, 20–40 tests each): ledgerly, stockroom, slotbook, ratekeeper, csvflow
- [x] Bug shapes: deep call chain · one root cause/many failures (spec 3–6; verified 3–8; only ledgerly rounding-mode has 8) · regression trap · misleading surface; mutation operators per SPEC §3
- [x] 26 tasks: train 12 / gate 6 / heldout 8 (2 from a domain absent from train+gate)
- [x] Self-check: every pristine task fails, reference fix passes, fix is ≤3 lines, failing count matches shape
- [x] Held-out includes a `ledgerly` deep-call-chain + regression-trap task for the live demo (bug in `money.py`)
- [x] `growth/eval.py` runner per CONTRACT 2.2 (workdir copy, fakehome HOME, independent pass judging, tests-untouched check, round-0 cache)
- [x] Failure labeller (`tasks/labels.py`: process / knowledge / format): classify round-0 failures as process vs knowledge for the checkpoint
- [x] `tests/test_tasks_*.py`
- [x] `core` profile (3/3/3) alongside `full` (12/6/8): `--profile core|full`
- [x] Round-0 checkpoint (real qwen3.5:4b, 5 full-train tasks, 240 s budget): **1/5 pass, 11.2 model calls/task; failures = 4 process, 0 knowledge, 0 format.**
  Pattern: the student reads file after file (it even opens the buggy module in 4/4 failures) but never commits to an edit,
  never follows the traceback; the one pass then re-ran the tests 5x. Evidence: `.manifest/runs/20261003-132023-checkpoint-round0-240s.jsonl`.
  A first attempt at 120 s was invalid: the laptop was swapping (6.3 GB) and calls never returned -> labelled `budget`.

## B — harness (`harness/`, `routines/seed/`, `routines/registry.json`)
- [ ] `student.py` Ollama client: `think=False`, temp 0, `num_ctx 16384`, 768 out tokens; `.chat` + `.ask` (pydantic-validated, re-ask once); logs `model.call` with tokens/ms
- [ ] `tools.py` 5 tools, path jail to workdir, manifest enforcement + `warden.block`, pytest output parsed into failures/frames
- [ ] `loop.py` baseline tool-calling loop (12 steps / 120 s)
- [ ] `state.py`, `controller.py` (registry order, first `applies`, Executor protocol), seed routines `start` + `ask-student` ONLY
- [ ] `run.py` `run_task` per CONTRACT 2.3; `python -m harness.run <taskdir> --mode baseline|manifest`
- [ ] Smoke: baseline on 1 real task end-to-end with events
- [ ] `tests/test_harness_*.py` (fake student)

## C — grow (`growth/grow.py`, `growth/gate.py`, `harness/teacher.py`)
- [ ] Teacher client (DeepSeek, OpenAI-compatible), JSON schema validation + 1 retry, cost tracking, `model.call` role=teacher
- [ ] Trace compressor: function-level failed traces from train events only (≤6, bounded)
- [ ] Teacher prompt per SPEC §5.2; proposal → `growth.proposal`
- [ ] Gate: accept iff gate passes ↑ (or = with model calls ↓ ≥20%) and no regression → `gate.result`
- [ ] Accept: copy to `routines/grown/<name>/`, export `skills/<name>/` (SKILL.md + `scripts/routine.py`), insert into registry before `ask-student`
- [ ] Held-out eval each round → `eval.heldout`; 4 rounds; stop after 2 consecutive rejections; `run.end` summary
- [ ] Leak test: no held-out id/content in any teacher prompt
- [ ] One full round on 3 train + 2 gate tasks (dry-run mode with a fake teacher too)

## D — warden (`warden/`, `skills/warden/`, `demo/`, `.github/workflows/skills.yml`)
- [ ] FIRST 20 MIN: `sandbox-exec` profile proven to block `~/.ssh` read + outbound network, while allowing python, pytest, workdir writes under `src/**`, and localhost:11434
- [ ] `sandbox.py` SandboxExecutor (profile generated from manifest, `HOME=demo/fakehome`); honest fallback if sandbox-exec fails
- [ ] `scan.py` regex/AST rules (network, shell subprocess, eval/exec/b64, out-of-dir paths, env reads) + optional teacher deobfuscation
- [ ] `manifest.py` build + verdict; `cli.py` bordered permission card; `manifest warden audit`, `manifest skill add [--force-run]`
- [ ] `skills/warden/` Agent Skill (agentskills.io spec) + `scripts/audit.py`
- [ ] `demo/thirdparty-skills/quick-fix-pro` (rigged, harmless: reads fake `~/.ssh`, posts to `demo/sink.py` on localhost) → DANGEROUS card; force-run → `warden.block`, sink receives nothing
- [ ] CI: `skills-ref validate skills/*`

## E — gui (`gui/`)
- [ ] Vite + React + TS; reads `.manifest/runs/*.jsonl` (tiny dev-server middleware lists/streams files)
- [ ] Realistic fake run (3 rounds, one Warden rejection, one `warden.block`) in `gui/fixtures/`
- [ ] Top bar (student/teacher/ONLINE-OFFLINE badge via `navigator.onLine` + run flag, round) · Task board · Live trace (code rows vs model rows) · Growth timeline (proposal → Warden card → gate → stamp) · Results (held-out by round, model calls by round, teacher cost)
- [ ] Replay (1×–20×, scrub by round) + Live (tail newest file)
- [ ] `/impeccable critique` + `/impeccable polish`; deliberate, not a default dashboard
- [ ] Works fully offline (no CDN fonts at runtime — bundle them)
