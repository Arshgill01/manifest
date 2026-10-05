---
name: fix-failures
description: "Repairs a failing pytest suite one verified edit at a time: refresh the full-suite result, take the innermost non-test traceback frame of the next unrepaired failure, ask one focused question for a single minimal search/replace edit, apply it, re-run the whole suite, and revert the edit when the suite gets strictly worse."
license: MIT
metadata:
  source: "manifest-grown"
  round: "1"
  teacher: "deepseek-flash"
  warden-verdict: "ok"
---

# Traceback-first repair

Never let the repair loop wander. Each pass of the controller is one of two deterministic acts:

1. **Refresh.** If no full-suite result exists, or source has been edited since the last run, run
   the whole suite. If the failure count went up, undo the newest edit -- a regression never stays.
   If nothing fails, the task is done.
2. **Repair.** Otherwise take the innermost non-test traceback frame of the next unrepaired
   failure, show the student that file's enclosing function and the failing line, and ask for
   exactly one minimal search/replace edit. Apply it, then immediately refresh again.

Rules for the student: one question, one edit, verbatim `search` text, never touch `tests/`. Each
location is tried at most twice (the second question is worded differently); when no patchable
source frame is left the routine stops applying and the generic tool-calling fallback takes over.

## How Manifest uses it

Grown by Manifest's growth loop in round 1 (teacher: `deepseek-flash`); never hand-written.
`scripts/routine.py` exports `NAME`, `applies(state)` (trigger) and `run(state, tools, student)`.
Trigger: Applies while the task is unsolved and either the full-suite result is stale (no run yet, or edits happened after the last run) or a traceback frame in non-test project source has been tried fewer than twice. Refreshes the suite (undoing edits that made it strictly worse), asks the student for one minimal search/replace edit at the innermost failing project frame, and verifies it immediately.

## Permissions (Warden manifest)

- read: **
- write: src/**
- commands: python -m pytest
- network: false
- verdict: ok
