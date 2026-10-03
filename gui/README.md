# Manifest GUI

A **read-only viewer** over `.manifest/runs/*.jsonl` (the event log in CONTRACT.md part 1). It replays a growth run
round by round, or tails the newest run live. It never controls the harness. Vite + React + TypeScript, no UI or chart
libraries, no CDN: the build works with Wi-Fi off.

```bash
cd gui
npm install
npm run dev        # http://127.0.0.1:5173  (serves /api/runs from ../.manifest/runs)
npm run serve      # production build + preview on :4173, same API, fully offline
npm test           # vitest: parser, derive, trace grouping against the fixture
```

`MANIFEST_RUNS_DIR=/some/dir npm run dev` points it elsewhere. With no server at all (any static host), the bundled
fixture still loads, and any `.jsonl` can be dropped onto the window or opened with **+**.

## What's on screen

| Area | Shows |
|---|---|
| Sidebar | runs (newest first), **Go live**, the task board (held-out first, then train, gate; one pip per round, ✓/✕ glyphs), student + teacher |
| Header | run, mode, round, and the big **ONLINE / OFFLINE** pill (`navigator.onLine`, or a run started with `online:false`) |
| Trace tab | one task attempt. **Code routines** are steel boxes in mono (ƒ). **Student model calls** are amber pills in a serif italic (4B). Warden blocks are vermilion. "Who drove" counts code decisions vs student calls. |
| Results tab | held-out pass rate by round, student model calls per task by round, the teacher bill |
| Composer | the replay transport: round-segmented scrubber with clickable story beats (proposal ◆, accepted ●, rejected ●, Warden block ■), mode, speed 1×–20×, play |
| Growth panel | per round: proposed routine + rationale → Warden permission card → gate before→after → ACCEPTED/REJECTED stamp, plus any runtime Warden blocks |

Keys: `space` play/pause · `←/→` rounds · `1–5` speed · `L` live · `G` growth panel · `Esc` follow the run · `?` help.
Deep links: `?pin=ledgerly-07:3` · `?at=1200` · `?play`. Theme: dark by default; the sun/moon toggle gives a light
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
