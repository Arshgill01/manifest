#!/usr/bin/env bash
# Bot lane guard. Usage: lane-guard.sh <head-branch>  (changed paths, one per line, on stdin)
#
# Branches named bot/<lane>/<ticket> may only touch their lane's paths (AGENTS.md) and never the
# protected core. Bots must not use devin/* branches, which would skip the check. Any other branch is a
# human branch and passes; protected paths are still covered by CODEOWNERS review.
# Exit 0 = allowed, 1 = violation, 2 = usage error.
set -uo pipefail

ref=${1:-}
[[ -z "$ref" ]] && { echo "usage: lane-guard.sh <head-branch> < changed-paths" >&2; exit 2; }

if [[ "$ref" == devin/* ]]; then
  echo "::error::Branch '$ref': fleet Bots must work on bot/<lane>/<ticket>, not devin/*."
  exit 1
fi
if [[ "$ref" != bot/* ]]; then
  echo "Human branch '$ref': lane guard not applied."
  exit 0
fi

lane=$(cut -d/ -f2 <<<"$ref")
ticket=$(cut -d/ -f3- <<<"$ref")
if [[ -z "$ticket" ]]; then
  echo "::error::Branch '$ref' must be bot/<lane>/<ticket>."
  exit 1
fi

# The evaluation core: what defines, runs or scores an experiment, and the rules themselves.
PROTECTED='^(SPEC\.md|CONTRACT\.md|CLAUDE\.md|AGENTS\.md|growth/|harness/|tasks/splits\.json|pyproject\.toml|uv\.lock|\.github/(CODEOWNERS|scripts/|workflows/bot-lane-guard\.yml))'

case "$lane" in
  lab-runner)      ALLOWED='^(\.manifest/(runs/|cache/|growth/|queue\.txt$|teacher-ledger\.jsonl$)|harnesses/|experiments\.json$|RESULTS\.md$)' ;;
  bug-smith)       ALLOWED='^(tasks/(gen\.py|mutations\.py|labels\.py|index\.json|README\.md|templates/|generated/)|tests/test_tasks_[^/]*\.py$)' ;;
  red-team)        ALLOWED='^(warden/|skills/warden/|demo/(thirdparty-skills/|fakehome/|sink\.py$)|tests/test_warden_[^/]*\.py$)' ;;
  registry-keeper) ALLOWED='^(skills/|\.github/workflows/skills\.yml$)' ;;
  referee)
    echo "::error::Referee is review-only and cannot open PRs that change files."
    exit 1 ;;
  *)
    echo "::error::Unknown lane '$lane'. Lanes: lab-runner, bug-smith, red-team, registry-keeper, referee."
    exit 1 ;;
esac

fail=0 n=0
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  n=$((n + 1))
  if [[ "$f" =~ $PROTECTED ]]; then
    echo "::error file=$f::Protected path: lane '$lane' may not change '$f' (evaluation core; human-only)."
    fail=1
  elif [[ ! "$f" =~ $ALLOWED ]]; then
    echo "::error file=$f::Outside lane: '$lane' may not change '$f'."
    fail=1
  fi
done

[[ $fail -eq 0 ]] && echo "Lane '$lane': all $n changed paths are inside the lane."
exit $fail
