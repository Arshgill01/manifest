---
name: root-cause-patch
description: "When a pytest suite has several failures and the student keeps reading files or narrating a diagnosis without editing, stop the conversation and force one concrete, verified patch aimed at the shared root cause across all failing tests."
license: MIT
metadata:
  source: "manifest-grown"
  round: "17"
  teacher: "deepseek-flash"
  warden-verdict: "ok"
---

# Root-cause patch

Use this when a suite has multiple failures and the run is stuck in a read-only spiral: the
student opens file after file (or writes a correct diagnosis in prose) and never edits, so the
suite never moves.

What it does:
1. Re-runs the suite and takes up to four remaining failures.
2. Collects the source modules imported by every failing test file (not just the first test),
   plus the deepest non-test traceback frame, and shows their bodies.
3. Asks one short question: give the file and one exact search/replace block that fixes as many
   of these failures as possible. Never edit tests/.
4. Applies the block, re-runs the suite, and reverts it if the failure count got worse.

Budget: at most twice per task, at least 3 student turns apart, first firing after 2 student turns.

## How Manifest uses it

Grown by Manifest's growth loop in round 17 (teacher: `deepseek-flash`); never hand-written.
`scripts/routine.py` exports `NAME`, `applies(state)` (trigger) and `run(state, tools, student)`.
Trigger: Fires early (after 2 student turns) whenever a failing suite remains, then again at most once every 3 student turns, up to 2 times per task. It interrupts the read-only spiral by presenting all remaining failures plus every source module imported by the failing test files and forcing one applied, verified patch.

## Permissions (Warden manifest)

- read: **
- write: src/**
- commands: python -m pytest
- network: false
- verdict: ok
