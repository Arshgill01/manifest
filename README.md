# Manifest

**A coding-agent harness that grows itself.**

A 4B model on a laptop is smart enough to fix most bugs. It fails as an agent because of *process*:
it wanders, re-reads, never commits to an edit, never re-runs the full suite. Manifest watches it fail
on practice tasks, shows a frontier **teacher** (DeepSeek V4.1 Flash, MIT open weights) those failures
as function-level execution graphs, and lets the teacher grow the missing control flow **as code**.
Every candidate must repair the failures it was shown, must not lower a separate gate set, and must earn
a **permission manifest** from **Warden**. The grown harness then runs **fully offline** with the 4B
model (Qwen3.5-4B via Ollama), and every line the teacher wrote runs inside a kernel sandbox.

> Taught once online. Runs offline forever. Your code never leaves your machine.

Built in one day at a hackathon (October 3, 2026), where it placed **3rd**. Since then it has been an
ongoing research project (**v2**): a faithful implementation of the paper it builds on, a larger
verified task suite, a Linux kernel sandbox, and statistics behind every number.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/gui-home-dark.png">
  <img alt="The Manifest GUI: New run, set to run the grown harness on the held-out demo tasks with qwen3.5:4b" src="docs/images/gui-home-light.png">
</picture>

---

## Status and results

**v2 experiments are running.** [`RESULTS.md`](RESULTS.md) is regenerated from the committed event logs by
`growth/results.py` (task-level bootstrap CIs, paired comparisons, exact McNemar tests). The experiment plan
is in [`SPEC.md` §9](SPEC.md) and progress in [`ROADMAP.md`](ROADMAP.md).

| id | experiment | status |
|---|---|---|
| E1 | baseline tool-calling loop, student only, 66 tasks | running |
| E2 | h0 (seed controller) on the 26-task held-out | queued |
| E3 | the hackathon harness (`triage-fix`) on the 26-task held-out | queued |
| E4/E5 | v2 growth run (paper Algorithm 1) → final harness once on held-out | queued |
| E6–E8 | ablations, budget sensitivity, Warden at run time | planned |

### Hackathon results (v1, kept for the record)

Measured on an 8 GB M1 laptop with a 240 s wall clock per task, `core` profile (3 train / 3 gate / 3
held-out); full tables in [`docs/history/RESULTS-hackathon.md`](docs/history/RESULTS-hackathon.md).

| | Baseline (plain tool loop) | Grown harness |
|---|---|---|
| Held-out model calls per task | 7.3 | **4.3 (41% fewer)** |
| Held-out pass rate | 1/3 | 1/3 |
| Gate pass rate | 0/3 | **2/3**, no regressions |
| Teacher cost, whole run | | **$0.014** |

The teacher grew [`triage-fix`](routines/grown/triage-fix/routine.py) (run the full suite, follow the
traceback to the innermost frame of your own code, ask for one search/replace patch, re-run). The sample
was tiny and the pass rate did not move; v2 exists to find out what is actually true.

![The teacher proposes triage-fix; Warden grants it write src/**, run python -m pytest, no network](docs/images/gui-session-triage-fix.png)

---

## How it works (v2)

```
 train stream ──► current harness h runs each task ──► failures fill a window W (K tasks)
                                                              │
         teacher sees h's code + W as function-level execution graphs + diagnostics (train only)
                                                              │
     proposes ONE change set (≤ L functions; only routines that ran in W; no deletions; generic)
                                                              │
                 validate ──► Warden scan + permission manifest ──► re-run on W (≥ Q repaired?)
                                                              │
       gate: success on unseen gate tasks must not drop ──► accept (h moves on)  or  roll back
                                                              │
           W keeps unsolved tasks with fresh traces; a task retires after R_max failed repairs
                                                              │
         final harness h* ──► evaluated ONCE on held-out ──► promoted to Agent Skills (skills/)
```

| Part | Where | What it does |
|---|---|---|
| Student | `harness/student.py` | Qwen3.5-4B on Ollama, temperature 0, thinking off; fixed-format, schema-validated questions, re-asked once. |
| Baseline | `harness/loop.py` | Plain tool-calling loop (list, read, run tests, edit, bash): the paper's *Tool-Calling* baseline. Accepts common argument synonyms so a schema quirk can't sink it. |
| Controller | `harness/controller.py` | Code loop over routines: `applies(state)` decides when a routine fires, `run(state, tools, student)` what it does. h0 = two minimal seeds. |
| Execution graph | `harness/fntrace.py` | Every function in a routine is traced (`fn.call` / `fn.return`), so traces show routine → functions → tool/student calls. |
| Teacher | `harness/teacher.py`, `harness/budget.py` | Proposes multi-routine change sets; JSON + constraint validation with one repair retry; DeepSeek peak/off-peak prices, persistent spend ledger, hard caps. |
| Growth | `growth/stream.py`, `growth/validate.py` | The paper's failure-window loop: K, R_max, Q, edit budget L, trace scope, no deletions, specificity lint, gate + transactional rollback, checkpoint/resume, versioned harnesses (`harnesses/<run>/h<k>.json`). |
| Warden | `warden/` | Static scan + teacher deobfuscation → permission manifest; runtime enforcement with **bubblewrap** (Linux) or `sandbox-exec` (macOS): grown routines' `run()` and `applies()`, tool subprocesses, and the judge all run with no network and no `$HOME`. |
| Tasks | `tasks/` | **68 tasks** on 5 services (26 + 2 demo from v1, 40 added in v2, append-only). Bug shapes mechanically verified. [`tasks/README.md`](tasks/README.md) |
| Runner | `growth/eval.py` | Runs any harness over a split; judges independently (re-runs the suite, fails any test-file tampering); per-task resumable cache; records host + budget. |
| Results | `growth/results.py`, `growth/stats.py` | RESULTS.md from logs only: bootstrap CIs, paired deltas, McNemar, failure labels, growth timeline. |
| GUI | `gui/` | Replays / live-tails event logs (v1 and v2 runs) and launches allow-listed runs. |

### What makes the evaluation trustworthy
- **Same budget for every harness**: 12 steps / 24 student calls per task; the wall clock (1800 s) is only a
  safety cap, because on a CPU-only machine a time budget measures the hardware, not the harness.
- **The harness never grades itself.** The runner re-runs the real suite (in the sandbox); tampering is a fail.
- **No leakage.** Root causes live only in `tasks/index.json`; the teacher sees only train traces; every
  held-out id of every profile and the held-out-only domain (`csvflow`) are checked out of every prompt.
- **No special-casing.** Routines mentioning task ids, domain or module names are rejected before they run.
- **Verified bug shapes**, an append-only suite (old results never go stale), host provenance on every run,
  and failures labelled `process / knowledge / format / budget`.

### Warden, live
```bash
uv run python -m warden.sandbox --selftest                                   # kernel sandbox: what is blocked, what is allowed
uv run manifest warden audit demo/thirdparty-skills/quick-fix-pro            # DANGEROUS: reads ~/.ssh, phones home, hides it
uv run manifest skill add demo/thirdparty-skills/quick-fix-pro --force-run   # runs sandboxed: blocked, the sink gets nothing
uv run manifest warden audit skills/triage-fix                               # a grown routine: OK within the default grant
```

---

## Run it

Requirements: Linux with `bubblewrap` (or macOS for `sandbox-exec`), Python 3.11+, [uv](https://docs.astral.sh/uv/),
Node 20+ for the GUI, and Ollama **0.35 or newer**. A GPU is not required (v2 numbers come from a 4-vCPU VM).

```bash
uv sync
curl -fsSL https://ollama.com/install.sh | sh        # or: brew install ollama && brew services start ollama
sudo apt-get install -y bubblewrap                   # Linux kernel sandbox
ollama pull qwen3.5:4b
cp .env.example .env                                 # teacher runs only: DEEPSEEK_API_KEY
uv run pytest                                        # ~280 tests, no models needed
```

```bash
uv run python -m growth.eval --split heldout --profile v2 --mode baseline --round 0       # baseline (cached per task)
uv run python -m growth.eval --split heldout --profile v2 --mode manifest \
       --registry harnesses/<run>/registry.json                                          # any grown harness
uv run python -m growth.stream --profile v2                                               # v2 growth (teacher, capped spend)
uv run python -m growth.stream --resume <run-id>                                          # continue after a stop
uv run python -m growth.stream --fake-teacher --stub-runner                               # rehearsal, no models
uv run python -m growth.results experiments.json -o RESULTS.md                            # results from logs
uv run python -m growth.promote harnesses/<run>/registry.json                             # export as Agent Skills
cd gui && npm install && npm run serve                                                    # http://127.0.0.1:4173
```

---

## Prior work: how v2 maps the paper

Builds on *"Grow the Harness, Not the Context"* (arXiv 2609.26760).

| Paper | Manifest v2 |
|---|---|
| Harness h, strategy-free scaffold h0 | routine registry; h0 = `start` + `ask-student` |
| Execution graph, function localisation ℱ(τ) | `routine.call` + `fn.call/fn.return` + tool/model calls; routines that ran = editable scope |
| Failure window (K, R_max), retirement | `growth/stream.py` (K = 4, R_max = 3) |
| Optimizer input Z = (h, window traces, diagnostics E) | harness source with scope marks, nested graphs, judge feedback + action statistics |
| Edit budget L, no deletions, no task-specific code | `growth/validate.py` (L = 10, function-level AST diff, specificity lint) |
| Repair threshold, gate SR ≥ checkpoint, transactional rollback | same; per-task regressions logged |
| Test set evaluated once | held-out evaluated once on h* |
| Ablations: no function guidance / no gate / K = 1 | `--ablate no-fn-trace / no-gate / window-1` |

Our additions: the coding domain with mechanically verified bug shapes; Warden as a gate on teacher-written
code and as runtime enforcement; grown routines exported as Agent Skills; fully offline deployment.

## Disclosures
- **AI-assisted.** The code was written with AI coding agents (Claude Code); the hackathon build used five
  parallel worktrees against a shared spec (archived in `docs/history/`). The GUI design used the Impeccable skill.
- **Grown routines are teacher-written** and never hand-edited; provenance is in the growth logs and in each
  routine's `proposal.json`.
- **Font:** Newsreader via `@fontsource-variable/newsreader` (SIL OFL), bundled for offline use.

## License
MIT. See [LICENSE](LICENSE).
