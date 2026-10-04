# CONTRACT.md (v2)

Interfaces that several parts of the repo (and the GUI) depend on. Change them deliberately: update this
file, the producers, the consumers and the tests in the same commit. The hackathon version is in
`docs/history/CONTRACT-hackathon.md`; v2 only **adds** fields and event types, so v1 logs still replay.

# Part 1: Event log (`.manifest/runs/<YYYYMMDD-HHMMSS>-<label>.jsonl`)

One JSON object per line, appended and flushed per line (the GUI tails files live). Every event has
`{ts, type, round, taskId, split}`; `ts` is ISO-8601 UTC with milliseconds; `round` is an int (0 = baseline;
in v2 growth runs it is the optimisation step t); `split` ∈ `train | gate | heldout | null`. camelCase
field names; extra fields allowed; consumers ignore unknown fields **and unknown types**. Write only via
`harness.log.EventLog` (it rejects unregistered types).

| type | fields |
|---|---|
| `run.start` | `mode, student, teacher, online` · v2: `host{hostname,cpu,cpus,ramGb,ollamaVersion,modelDigest,studentOptions,codeHash,…}`, `maxSteps, maxSeconds, registry, executor, profile` |
| `task.start` | `domain, bugShape` · `mode` |
| `task.end` | `pass, steps, modelCalls, routineCalls, ms` · `judge{passed,failed,expected,testsUntouched,tampered}`, `stopReason`, `selfReportedDone`, `overtime`, `error?` |
| `routine.call` | `routine, summary, ms` · `source: seed\|grown`, `ok` |
| `model.call` | `model, role: student\|teacher, purpose, promptTokens, outTokens, ms` · `cacheHitTokens?`, `costUsd?`, `doneReason?`, `prompt`, `response` (excerpts), `error?`, teacher: `peak`, `attempt` |
| `tool.call` | `tool, args, ok, summary` · `skill` |
| `fn.call` | **v2** `routine, fn, depth, args{name: short repr}` |
| `fn.return` | **v2** `routine, fn, depth, ms, ret \| exc` |
| `growth.proposal` | `routine, rationale, triggerDescription, skillPath` · v2: `changes[{name, edit, functionsChanged[]}]`, `step` |
| `warden.manifest` | `skill, read[], write[], commands[], network, findings[], verdict` |
| `warden.block` | `skill, attempted, reason` · `enforcement` |
| `gate.result` | `routine, accepted, gateBefore, gateAfter, regressions[], modelCallsBefore, modelCallsAfter` · `rejectReason`, `gateTotal` |
| `growth.window` | **v2** `step, cursor, window[{taskId, attempts}], retired[], solvedOnFill[]` |
| `growth.repair` | **v2** `step, candidate, solved[], unsolved[], threshold, ok` |
| `growth.step` | **v2** `step, outcome: accepted\|rejected, stage: validate\|warden\|repair\|gate\|accepted, reason, changes[], dFun, harness` |
| `growth.checkpoint` | **v2** `step, path, harness` |
| `eval.heldout` | `passed, total, avgModelCalls` |
| `run.end` | `summary` (v1 growth: `heldoutByRound, avgModelCallsByRound, teacherCostUsd, routinesAccepted`; v2 growth: `steps, accepted[], final harness, teacherCostUsd, stopReason`) |

# Part 2: Python seams

## 2.1 Task on disk
```
tasks/generated/<task-id>/          # the only thing a model or harness ever sees
  TASK.md   src/<pkg>/*.py   tests/test_*.py   conftest.py   pytest.ini
tasks/splits.json                   # {"seed", "novelDomain", "train", "gate", "heldout", "profiles": {name: {train, gate, heldout}}}
tasks/index.json                    # {id: {domain, bugShape, mutation, rootCause{file,function,line,span}, failingTests, passingTests, fix}}
```
Task id `<domain>-<nn>`. Tests run with `python -m pytest -q -p no:cacheprovider` from the task dir.

## 2.2 Runner: `growth/eval.py`
```python
run_split(split, *, mode, round, log, registry=None, task_ids=None, profile="core",
          max_steps=12, max_seconds=1800, executor=None, use_cache=True) -> SplitResult
# SplitResult = {split, mode, round, profile, passed, total, avgModelCalls, results: [TaskOutcome]}
# TaskOutcome = {taskId, pass, steps, modelCalls, routineCalls, ms, judge, error, events: [dict]}
```
Round-0 baseline outcomes are cached per task in `.manifest/cache/round0/<config_key>/<task>.json`
(key: student model + digest + options, budget, host, `BASELINE_VERSION`). `mode`: `baseline | manifest |
oracle | noop`.

## 2.3 Harness entry: `harness/run.py`
```python
run_task(workdir, *, mode, log, registry=None, max_steps=12, max_seconds=120, executor=None, student=None)
    -> {steps, modelCalls, routineCalls, selfReportedDone, stopReason}
```
`Tools(workdir, manifest|None, log, skill=, deadline=)`: `list_files() -> [str]`, `read_file(path, start, end)
-> str`, `run_tests(selector=None) -> {passed, failed, errors, ok, exitCode, output, failures[{test, error,
frames[{file,line,function}]}]}`, `edit_file(path, search, replace) -> {ok, path, error, replacements}`,
`bash(cmd) -> {ok, exitCode, output}`. `Student(log)`: `.chat(messages, tools)`, `.ask(purpose, prompt, schema)`.
`State`: pydantic, JSON-serialisable, mapping-style access too.

## 2.4 Routines, registries, executors
```python
# <dir>/routine.py
NAME = "kebab-name"
def applies(state) -> bool: ...
def run(state, tools, student) -> state: ...
```
Registry JSON = ordered `[{"name", "path", "source": "seed|grown"}]`, `start` first, `ask-student` last, grown
in between. Paths are repo-relative or absolute. A routine dir may hold `manifest.json` (Warden), `SKILL.md`,
`proposal.json`. Executor protocol: `run(routine_dir, state, tools, student, manifest) -> State`, optional
`applies(routine_dir, state, manifest) -> bool`, `describe() -> str`. `warden.sandbox.make_executor(kind, log)`
with kind `auto | sandbox | inprocess`.

## 2.5 Teacher
`Teacher(log, budget=…)`: `.propose(context) -> {name, rationale, trigger_description, routine_py, skill_md,
requested_permissions}` (v1), `.propose_changes(context) -> {rationale, changes[...], order?}` (v2),
`.summarize_code(src) -> [str]`. Every call: `model.call` (role teacher, tokens, `costUsd`, `peak`) and a
ledger line in `.manifest/teacher-ledger.jsonl`. Raises `TeacherBudgetExceeded` before a call that the
budget cannot cover.

## 2.6 Warden
```python
warden.scan.scan(path, teacher=None) -> [{rule, severity, file, line, detail}]
warden.manifest.build(skill_dir, requested, findings) -> {skill, read, write, commands, network, findings, verdict}
warden.sandbox.SandboxExecutor(log)  # Executor; bwrap (Linux) | sandbox-exec (macOS) | audit-hook fallback
warden.sandbox.tool_argv(argv, workdir) -> argv   # kernel-sandboxed tool subprocess
```
