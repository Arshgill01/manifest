# Manifest: agent guide

Read `SPEC.md` (v2) and `CONTRACT.md` before changing code. `ROADMAP.md` is the working plan. The hackathon
docs in `docs/history/` are provenance only; do not follow their rules (worktree tracks, frozen specs, 240 s).

## Rules that matter
- **Never hand-write grown routines** (`harnesses/*/routines/`, `routines/grown/`, `skills/<grown>/`). They come
  from the teacher, with provenance in a growth log. Seeds (`routines/seed/`) stay minimal.
- **Nothing held-out reaches the teacher.** Teacher contexts go through `assert_no_leak`; keep the leak tests green.
- **Numbers come from logs.** `RESULTS.md` is generated (`growth/report.py`); never hand-edit results.
  Commit the event logs (`.manifest/runs/*.jsonl`) that back any reported number.
- Events only via `harness.log.EventLog`; a new event type must be registered there and documented in CONTRACT.md.
- Changing baseline behaviour (loop, tools, student call) → bump `harness.env.BASELINE_VERSION` so the round-0
  cache is not reused across incompatible runs.
- Never commit `.env`. Teacher spend is capped (`TEACHER_BUDGET_USD`, `--teacher-budget`); prefer off-peak.

## Environment (this machine)
- Debian VM `skywalker`, 4 vCPU, 8 GB RAM, **CPU only**. Student = `qwen3.5:4b` on the systemd Ollama
  (`http://localhost:11434`): ~60–90 s per student turn, a baseline task is 15–20 min. Never run two
  Ollama-backed suites at once and don't load other models (8 GB).
- Long runs go in tmux (`tmux new-window -t main -n <name> ...`), with console output in `.manifest/logs/`.
  Runs are resumable: round-0 baseline is cached per task; growth checkpoints in `.manifest/growth/<run>/`.
- Python via uv: `uv sync`, `uv run pytest` (~200 tests, ~1.5 min, no models needed), `uv run python -m ...`.
- Warden's kernel sandbox on Linux is bubblewrap (`/usr/bin/bwrap`); `uv run python -m warden.sandbox --selftest`.
- Teacher key: `DEEPSEEK_API_KEY` in `.env` (template `.env.example`), model id `deepseek-flash`.

## Common commands
```bash
uv run python -m growth.eval --split heldout --profile full --mode baseline --round 0          # E1 (cached per task)
uv run python -m growth.eval --split heldout --profile full --mode manifest --registry <reg>   # any harness
uv run python -m growth.stream --profile full                                                  # v2 growth (teacher)
uv run python -m growth.stream --fake-teacher --stub-runner                                    # rehearsal, no models
uv run python -m growth.report <log.jsonl> [...] -o RESULTS.md
uv run python -m tasks.labels <log.jsonl>
```

## Working style
- Commit at each checkpoint with a clear message (no AI attribution lines). Tick items in `ROADMAP.md`.
- Tests live in `tests/`; anything touching the event log, the teacher context, Warden or judging needs a test.
- Report honestly: failed runs, budget hits and deviations go into RESULTS.md notes, not under the rug.
