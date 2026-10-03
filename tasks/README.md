# Task suite

26 debugging tasks across 5 small but realistic Python services. Each task is a clean package
with **exactly one injected root-cause bug** and a pytest suite that now fails. The instruction is
always the same: *"The test suite is failing. Make it pass without editing tests."*

| Domain | What it is | Modules | Source lines | Tests | Tasks |
|---|---|---|---|---|---|
| `ledgerly` | invoices, line items, tax (incl. VAT-inclusive), coupons, cent-exact allocation, payments, aging | 7 | 445 | 40 | 7 |
| `stockroom` | multi-location inventory, expiring reservations, reorder points, FIFO valuation | 6 | 311 | 32 | 6 |
| `slotbook` | room booking, half-open time ranges, overlap/gaps, fixed-offset time zones, recurrence | 6 | 283 | 32 | 6 |
| `ratekeeper` | token bucket, sliding/fixed windows, daily quotas, Retry-After headers (exact `Fraction` time) | 6 | 247 | 24 | 5 |
| `csvflow` | CSV ingest, schema coercion, row-level issues, transforms, grouping stats | 6 | 238 | 21 | 2 |

`csvflow` appears **only in held-out**: it measures whether grown routines generalise to a codebase
the teacher never saw.

## Bug shapes are verified, not claimed

`tasks/mutations.py` declares each bug as data (operator, root function, claimed shapes).
`python -m tasks.gen` builds every task in a scratch directory and refuses to emit it unless:

1. the clean template passes, the mutated package fails, and reverting the mutation passes again;
2. every claimed shape holds mechanically:
   - **deep-call-chain**: no failing test lives in the root module's own test file (you must follow calls down);
   - **one-root-many**: 3–8 tests fail from the single defect;
   - **regression-trap**: a declared *tempting local fix* clears a failure **and** breaks a test that was passing
     (so you must re-run the full suite and roll back);
   - **misleading-surface**: every crash surfaces outside the root-cause function (callee defect, caller blows up).

Operators used: wrong comparison, off-by-one (range/slice/index), missing return, swapped arguments,
wrong rounding mode, wrong default, inverted condition/sign.

## Splits

`splits.json` holds two profiles, both deterministic (seed 1337) and stratified by bug shape:

| profile | train | gate | held-out | use |
|---|---|---|---|---|
| `full` | 12 | 6 | 8 (2 novel-domain) | SPEC §3 |
| `core` | 3 | 3 | 3 (1 novel-domain) | fits a full growth run on an 8 GB laptop |

Root-cause metadata lives only in `index.json`, never inside a task directory; no model sees it.
The teacher only ever sees train-split traces.

**Live-demo task (`ledgerly-01`)**: invoice tests fail with `ValueError: weights must sum to a positive
number`; the traceback ends in `money.allocate` (deep call chain). Deleting the guard is the
tempting fix, and it breaks `test_allocate_rejects_bad_input` (regression trap). The real fix is one character.

## Judging (growth/eval.py)

The harness never grades itself. After it returns, the runner re-runs the real suite in the task's
working copy and marks the task passed only if **every** original test passes **and** no test-side file
(`tests/**`, any `conftest.py`, pytest config, `.pth`, `sitecustomize`) was changed or added.
`tests/test_tasks_eval.py` proves editing, deleting or shadowing tests is caught.

```bash
uv run python -m tasks.gen                    # rebuild + verify all 26 tasks
uv run python -m growth.eval --split train --mode baseline --round 0 --profile core
uv run python -m growth.eval --split train,gate,heldout --mode oracle   # reference fixes: must be 100%
uv run python -m tasks.labels .manifest/runs/<run>.jsonl               # process / knowledge / format
```
