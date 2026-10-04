#!/usr/bin/env bash
# Run model-backed jobs strictly one after another (8 GB, one Ollama model): each line of the queue file is
# "<label>|<command>"; finished labels are recorded in .manifest/logs/queue.done so the queue is resumable.
# Usage: scripts/queue.sh .manifest/queue.txt
set -u
cd "$(dirname "$0")/.."
Q=${1:-.manifest/queue.txt}
DONE=.manifest/logs/queue.done
mkdir -p .manifest/logs; touch "$DONE"
while true; do
  line=$(grep -v '^#' "$Q" | grep -v '^\s*$' | while IFS='|' read -r label cmd; do
           grep -qxF "$label" "$DONE" || { echo "$label|$cmd"; break; }; done)
  [ -z "$line" ] && { echo "[queue] empty $(date)"; break; }
  label=${line%%|*}; cmd=${line#*|}
  echo "[queue] $(date '+%F %T') start $label: $cmd"
  bash -c "$cmd" > ".manifest/logs/$label.log" 2>&1
  rc=$?
  echo "[queue] $(date '+%F %T') end $label rc=$rc"
  echo "$label" >> "$DONE"
done
