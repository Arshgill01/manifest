# Manifest GUI

A desktop-app-style GUI over `.manifest/runs/*.jsonl` (the event log in CONTRACT.md part 1). Every run is a **session**:
finished runs replay, and runs still being written tail live. **New run** starts the harness for you. It spawns the same
CLIs you'd type (`python -m growth.eval …`, `python -m growth.grow …`) and opens the session as the log fills, so the
harness itself stays headless and the event log stays the only interface. Vite + React + TypeScript, no UI or chart
libraries, no CDN: the build works with Wi-Fi off.

> SPEC §8 says "a viewer, never a controller". The launcher is a thin exception the owner asked for. It only spawns
> the documented CLIs with whitelisted arguments (no shell), one run at a time. It **refuses any model-backed run while
> a run file in any worktree of this repo is still being written** (8 GB laptop: never two Ollama suites at once).
> Self-tests (`oracle`) and growth rehearsals (`--fake-teacher --stub-runner`) don't touch Ollama and are always allowed.

```bash
cd gui
npm install
npm run dev        # http://127.0.0.1:5173  (serves /api/runs from ../.manifest/runs)
npm run serve      # production build + preview on :4173, same API, fully offline
npm test           # vitest: parser, derive, trace grouping against the fixture
```

`MANIFEST_RUNS_DIR=/some/dir npm run dev` points it elsewhere. With no server at all (any static host), the bundled
fixture still loads, and any `.jsonl` can be dropped onto the window or opened with **+**.

## New run

| Choice | Runs |
|---|---|
| Grown harness | `growth.eval --mode manifest --split <s> --profile <p> [--tasks …]` |
| Student alone | `growth.eval --mode baseline --round 0 --force …` (round-0 behaviour, cache skipped so you can watch it) |
| Growth run | `growth.grow --rounds N --profile <p>` (needs the teacher, so it's disabled when offline) |
| Growth rehearsal | `growth.grow … --fake-teacher --stub-runner` (no models) |
| Runner self-test | `growth.eval --mode oracle …` (no models) |

Profiles come from `tasks/splits.json` (core, full, demo, …). **Stop run** in the header sends SIGINT.

## What's on screen (inside a session)

| Area | Shows |
|---|---|
| Sidebar | **New run**, sessions (newest first; a pulsing dot = still being written), student + teacher |
| Header | session, Live/Replay, round, the big **ONLINE / OFFLINE** pill (`navigator.onLine`, or a run started with `online:false`), **Stop run** |
| Session tab | the run as a conversation: round dividers, one line per task (✓/✕, student calls, time). Click a line to open its trace: **code routines** in steel mono boxes (ƒ), **student calls** in amber pills with a serif-italic voice (4B, expandable to what it saw and said), Warden blocks in vermilion. The teacher's proposals arrive as messages with the Warden permission card, gate result and stamp. |
| Board · Growth · Results tabs | red→green task grid per round · proposal → Warden → gate per round · held-out pass rate, student calls per task, teacher bill |
| Composer | replay transport: round-segmented scrubber with clickable story beats, speed 1×–20×, play |

Keys: `space` play/pause · `←/→` rounds · `1–5` speed · `N` new run · `?` help.
Deep links: `?run=<file prefix>` · `?pin=ledgerly-07:3` · `?at=1200` · `?play`. Theme: dark by default; the sun/moon toggle gives a light
theme for washed-out projectors.

## Fixture and live simulation

- `fixtures/demo-run.jsonl` is **fake data** for building the viewer: 3 growth rounds after a baseline, round 2 rejected by
  Warden, one `warden.block`, held-out `ledgerly-07` going red → green. Regenerate with
  `uv run python gui/fixtures/make_fixture.py`. It's written through `harness.log.EventLog` with a simulated clock, and
  `tests/test_gui_fixture.py` checks it against the contract.
- `uv run python gui/fixtures/simulate_live.py --speed 8 [--from-round 3] [--offline]` re-emits the fixture into
  `.manifest/runs/…-simulated.jsonl` in real time to exercise Live mode. Delete that file afterwards; it isn't a real run.

## Reading real runs: assumptions worth knowing

- A `routine.call` is emitted when the routine **finishes** (it carries `ms`). Tool/model/block events since the previous
  `routine.call` are drawn inside it. Events after the last one show as "routine running…".
- `ask-student` is the seed fallback where the student picks the move, so it's drawn student-led, not as a code box,
  and doesn't count as a code decision.
- A Warden rejection may skip the gate. A `gate.result` with `gateAfter: null` (+ `rejectReason`) or no `gate.result` at
  all both render correctly.
- Task mode comes from `task.start.mode` if present, else round 0 = baseline.

Design context: `PRODUCT.md`, `BRIEF.md`; critique snapshots in `.impeccable/critique/`.
