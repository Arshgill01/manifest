# ROADMAP (v2, post-hackathon)

Tick as you go; each checkpoint is a commit. Experiments E1–E8 are defined in SPEC §9.

## Phase 0: platform + protocol
- [x] Ollama 0.35.1 + `qwen3.5:4b` on the Linux VM; throughput measured (SPEC §1)
- [x] Warden kernel sandbox on Linux (bubblewrap); sandbox tests run on Linux
- [x] Grown routines execute sandboxed (`run` + `applies`) during every eval; tool subprocesses sandboxed
- [x] Function-level trace (`fn.call` / `fn.return`)
- [x] v2 budget: 12 steps / 24 calls binding, 1800 s safety cap; per-task resumable round-0 cache; host provenance
- [x] SPEC v2, CONTRACT v2, CLAUDE.md; hackathon docs archived
- [x] Teacher: current DeepSeek prices with peak/off-peak, persistent spend ledger, hard caps, off-peak waiting

- [x] Baseline fairness: tool-argument synonyms + informative errors (BASELINE_VERSION 3)
- [x] Judge and tool subprocesses run in the kernel sandbox
- [x] GUI replays v2 growth runs; launcher uses v2 commands
- [x] `growth/promote.py` (export a v2 harness as Agent Skills); README v2

## Phase 1: evidence without the teacher
- [ ] E1 baseline on full train / gate / held-out (26 tasks)
- [ ] E3 hackathon harness on full held-out
- [ ] E2 h0 seed controller on full held-out
- [ ] Determinism check (repeat a subset)
- [x] `growth/stats.py`: bootstrap CIs, paired comparisons, McNemar; report v2

## Phase 2: paper-faithful growth
- [x] `growth/stream.py`: training stream, failure window (K, R_max), checkpoint/resume, transactional rollback
- [x] `growth/validate.py`: edit budget L (function-level AST diff), trace scope, no deletions, specificity lint
- [x] Multi-change teacher output; function-level trace rendering + offline diagnostics in the teacher context
- [x] Repair threshold Q on the window, gate SR ≥ checkpoint, per-task regressions logged
- [x] Rehearsal with fake teacher + stub runner; unit tests (leak, rollback, resume, budget)
- [ ] E4 real growth run on full train + gate; E5 h* once on held-out
- [ ] Promote h*: export grown routines as Agent Skills, CI validation

## Phase 3: confidence
- [x] Grow the task suite: 40 more verified bugs, append-only (suite v2, 68 tasks)
- [ ] One more held-out-only domain (new template)
- [ ] Baseline on the v2 tasks
- [ ] E6 ablations: no-gate, window-1, no-fn-trace
- [ ] E7 budget sensitivity (baseline at 24 steps)
- [ ] Second growth run (variance across growth runs)
- [ ] README + GUI updated to v2 results
