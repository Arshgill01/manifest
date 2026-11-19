#!/usr/bin/env bash
# Self-test for lane-guard.sh: every case states the branch, the changed paths and the expected exit code.
set -uo pipefail
G="$(dirname "$0")/lane-guard.sh"
pass=0 fail=0

check() {  # check <expected-exit> <branch> <path>...
  local want=$1 ref=$2; shift 2
  printf '%s\n' "$@" | bash "$G" "$ref" >/dev/null 2>&1
  local got=$?
  if [[ $got -eq $want ]]; then pass=$((pass + 1))
  else fail=$((fail + 1)); echo "FAIL: $ref [$*] expected $want, got $got"; fi
}

# Human branches pass; Bots on devin/* or a malformed bot branch do not.
check 0 feat/devin-bot-fleet-guards SPEC.md growth/eval.py
check 1 devin/1732000000-fix-thing tasks/gen.py
check 1 bot/lab-runner RESULTS.md
check 1 bot/unknown-lane/LIN-1 README.md
check 2 ""

# Lab Runner: run outputs only.
check 0 bot/lab-runner/LIN-12 .manifest/runs/20261120-010000-e2.jsonl .manifest/cache/round0/abc/x.json experiments.json RESULTS.md harnesses/20261120-growth2/h1.json .manifest/queue.txt
check 1 bot/lab-runner/LIN-12 growth/results.py
check 1 bot/lab-runner/LIN-12 harness/env.py
check 1 bot/lab-runner/LIN-12 .manifest/queue.txt.bak
check 1 bot/lab-runner/LIN-12 tasks/splits.json

# Bug Smith: the task suite, never the held-out assignment.
check 0 bot/bug-smith/LIN-20 tasks/generated/gradebook-13/TASK.md tasks/index.json tasks/templates/gradebook/x.py tests/test_tasks_appendonly.py
check 1 bot/bug-smith/LIN-20 tasks/splits.json
check 1 bot/bug-smith/LIN-20 tests/test_grow_leak.py
check 1 bot/bug-smith/LIN-20 RESULTS.md

# Red Team: Warden and its adversarial demo, plus Warden tests.
check 0 bot/red-team/LIN-31 warden/scan.py demo/thirdparty-skills/evil-skill/SKILL.md tests/test_warden_scan.py demo/sink.py
check 1 bot/red-team/LIN-31 growth/validate.py
check 1 bot/red-team/LIN-31 demo/sink.py.orig

# Registry Keeper: exported skills and their CI.
check 0 bot/registry-keeper/LIN-40 skills/root-cause-patch/SKILL.md .github/workflows/skills.yml
check 1 bot/registry-keeper/LIN-40 .github/workflows/bot-lane-guard.yml
check 1 bot/registry-keeper/LIN-40 .github/scripts/lane-guard.sh
check 1 bot/registry-keeper/LIN-40 routines/grown/triage-fix/routine.py

# Referee writes nothing. Nobody edits the rules.
check 1 bot/referee/LIN-50 RESULTS.md
check 1 bot/lab-runner/LIN-12 AGENTS.md
check 1 bot/red-team/LIN-31 .github/CODEOWNERS

echo "lane-guard selftest: $pass passed, $fail failed"
[[ $fail -eq 0 ]]
