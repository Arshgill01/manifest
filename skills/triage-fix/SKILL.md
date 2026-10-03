---
name: triage-fix
description: "Drives one deterministic repair cycle after the test suite has failed - runs the full suite, localises the suspect frame from the traceback, reads a bounded code window, asks the student for a single search/replace patch, applies it, and re-runs the full suite. Use it whenever a task has failing tests and nobody has yet turned the traceback into a concrete file/line plus an attempted edit."
license: MIT
metadata:
  source: "manifest-grown"
  round: "2"
  teacher: "deepseek-flash"
  warden-verdict: "ok"
---

# triage-fix

Turns a traceback into a location and a patch instead of a reading tour.

## What it does

1. Runs `pytest` with **no selector** so `last_full_run` is always a real full-suite result.
   If nothing fails, the task is marked done immediately.
2. Takes the first failure, drops test/conftest/site-packages frames, and keeps the
   innermost remaining project frame as `suspect` = `{file, line, function}`.
3. Reads a bounded window (20 lines back, 45 forward) into `context_snippet`.
4. Asks the student exactly one question — purpose `patch` — with the test, error,
   traceback and that window, and demands a verbatim search/replace for **that** file.
5. Applies it through `edit_file` (never under `tests/`) and re-runs the full suite.

## Bounds

- At most 3 runs per task, then `ask-student` takes over.
- Two patches that cannot be applied set `triage_giveup`, and the routine stops applying.
- An already-seen `(file, search)` pair is never re-applied.

## When to use it

Right after `start`, on any task whose suite is red. Do not use it for semantic judgement —
that stays with the student; this routine only owns the sequence of steps around it.

## How Manifest uses it

Grown by Manifest's growth loop in round 2 (teacher: `deepseek-flash`); never hand-written.
`scripts/routine.py` exports `NAME`, `applies(state)` (trigger) and `run(state, tools, student)`.
Trigger: Runs immediately after `start` on any task that is not yet done, up to 3 times, and once more is disabled after two patches the student could not apply. It first runs the full suite (marking the task done if it is already green), then localises the top failure, and drives one diagnose-and-patch cycle.

## Permissions (Warden manifest)

- read: **
- write: src/**
- commands: python -m pytest
- network: false
- verdict: ok
