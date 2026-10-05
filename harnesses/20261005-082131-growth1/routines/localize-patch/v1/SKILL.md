---
name: localize-patch
description: "Localises a failing pytest test whose traceback points only at the test file by reading the test's own imports, then asks the student for one focused search/replace patch against the candidate source module and applies it to the candidate file that really contains the search text, re-running the full suite and reverting a patch that makes things worse."
license: MIT
metadata:
  source: "manifest-grown"
  round: "11"
  teacher: "deepseek-flash"
  warden-verdict: "ok"
---

# When to use
A failing test's traceback has no frame outside `tests/`, so the buggy line is never shown and the
student starts inventing file paths or reading forever.

# What it does
- Collects the test file's `import`/`from ... import ...` lines and maps them to existing repository
  files (`pkg/mod.py`, `.../pkg/mod/__init__.py`).
- Shows the student the failing test body and those candidate files, asking for one file plus a
  verbatim search/replace block.
- Applies the block to whichever candidate file literally contains the search text, so a wrong
  `file` in the answer is repaired instead of hitting the manifest block or a missing file.
- Re-runs the whole suite afterwards and reverts the patch if the failure count grew.

# Limits
At most three bounded attempts; after that it stops applying so the normal tool-calling fallback can
take over. It never fires when a real source frame exists (that case is left to forced-patch) and it
never edits `tests/`.

## How Manifest uses it

Grown by Manifest's growth loop in round 11 (teacher: `deepseek-flash`); never hand-written.
`scripts/routine.py` exports `NAME`, `applies(state)` (trigger) and `run(state, tools, student)`.
Trigger: At least one failing test has a traceback containing only tests/ frames (no source frame), the suite still fails, and the student has had a few tool-calling turns; runs up to 3 bounded patch attempts, each localising the module under test from the test file's imports and applying the student's search/replace to the candidate file that really contains it.

## Permissions (Warden manifest)

- read: **
- write: src/**
- commands: python -m pytest
- network: false
- verdict: ok
