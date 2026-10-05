---
name: forced-patch
description: "Interrupts a student that keeps reading files without editing. After several read-only turns with a failing suite it re-runs pytest, asks one short focused question about the failing test and the code at the deepest source frame, applies the returned search/replace patch, and reverts it if the suite gets worse."
license: MIT
metadata:
  source: "manifest-grown"
  round: "6"
  teacher: "deepseek-flash"
  warden-verdict: "ok"
---

# Forced patch

Long student contexts make the model narrate a diagnosis instead of editing files. When the suite is
still failing after several tool-calling turns with no edit at all, this routine takes over with one
short prompt: the failing test, its assertion error, and the code around the deepest non-test
traceback frame. The returned search/replace is applied through `tools.edit_file`, the suite is
re-run, and a patch that increases the number of failures is reverted. It runs at most twice per
task and never fires once a patch has been applied or the suite passes.

## How Manifest uses it

Grown by Manifest's growth loop in round 6 (teacher: `deepseek-flash`); never hand-written.
`scripts/routine.py` exports `NAME`, `applies(state)` (trigger) and `run(state, tools, student)`.
Trigger: Fires when the suite is still failing, at least four ask-student turns have produced no patch, and the routine has run fewer than twice; it re-runs the suite, asks one focused search/replace patch for the deepest source frame of the first failure, applies it, verifies, and reverts it if the suite got worse.

## Permissions (Warden manifest)

- read: **
- write: src/**
- commands: python -m pytest
- network: false
- verdict: ok
