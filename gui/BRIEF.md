# Design brief: Manifest run viewer (confirmed 2026-10-03)

> **Revised 13:05**: the owner asked for the feel of desktop agent apps (DeepSeek Harness, the ChatGPT macOS app,
> opencode, T3 Code). The shell is now dark by default: a sidebar of runs plus the task board, a header with tabs, a
> composer-style transport docked at the bottom, and a growth inspector on the right. The light "logbook" theme
> below survives as the projector toggle. Role colours, the code/model typography split and the Warden stamps carry
> over unchanged.

**Summary.** A single-screen Vite + React + TS viewer over `.manifest/runs/*.jsonl`. It replays (1×–20×, scrubbable by round) or live-tails the newest run, so judges can watch a 4B model's harness grow round by round, then watch it run with Wi-Fi off.

**Primary action.** Press play and watch the board go from red to green while the trace shows *code* routines doing the control.

**Direction.** Restrained, product register. Scene: a presenter on a bright hackathon stage, laptop mirrored to a washed-out 720p projector, judges 3 m away reading at a glance. That forces light and high-contrast. The lane is a flight-data recorder or lab logbook. Anchors: SBB departure boards (the board, tabular mono), Teenage Engineering manuals (precise labelled diagrams, one bold colour per role), NTSB flight-recorder plots (thin traces, annotated events).

**Role colours** (each used only for its role):
- steel blue (seed hue 210): code and routines
- amber/ochre: the student model
- ink: the teacher model
- vermilion: Warden refusals and blocks
- green and red: test outcomes, always with a ✓ or ✕ glyph

**Type.**
- Schibsted Grotesk: UI.
- Martian Mono: code, routines, numbers. It is condensed in trace rows, which suits a departure board.
- Newsreader italic: anything a model "said" (its purpose, rationale). That keeps the model's voice literally a different typeface from the machine's.

**Layout.**
- Top bar: wordmark, student, teacher, round, and the big ONLINE/OFFLINE badge.
- Transport row: mode, run picker, play, speed, round-segmented scrubber.
- Three columns: task board | trace | growth timeline.
- Results strip: held-out pass rate line, model calls per task columns, a teacher bill receipt.
- Fits 1280×720 without page scroll; panels scroll internally.

**States.**
- No runs yet: fixture offered, plus drop a `.jsonl`.
- Loading, malformed lines (skipped and counted), live waiting for the first event, live file rotated.
- Proposal rejected by Warden (no gate run).
- `warden.block` inside a trace.
- Task running vs pass vs fail vs not-run.
- Rounds not yet reached during replay.

**Fixture.** `gui/fixtures/demo-run.jsonl`, written through `harness.log.EventLog` with a simulated clock. It covers 3 growth rounds plus a baseline, round 2 rejected by Warden (network + env reads), one `warden.block` (the student tries to edit `tests/`), and a held-out `ledgerly` deep-chain task going red → green.
