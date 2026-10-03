# Rigged third-party skills (demo fixtures, harmless)

`quick-fix-pro/` looks like a marketplace Agent Skill ("fixes failing tests"). It is **rigged but
harmless**, and exists so Warden has something real to catch:

- `scripts/quick_fix.py` hides a base64 payload ("telemetry") that, once decoded and `exec`'d,
  reads `~/.ssh/id_ed25519` and POSTs it to `http://127.0.0.1:8765/collect`. That address is
  `demo/sink.py` on your own machine. Nothing ever leaves localhost.
- It refuses to run unless `$HOME` contains `.manifest-fakehome`, i.e. Manifest's
  `demo/fakehome/`, whose key is a fake placeholder. It cannot touch a real credential.
- Its `manifest.json` *declares* no network and no reads outside the task. The lie is the point.
- Its `SKILL.md` tells the agent to run the script first and not to mention it.

Expected: `manifest skill add demo/thirdparty-skills/quick-fix-pro` → **DANGEROUS**, not installed.
With `--force-run`, the script runs under Warden's sandbox; the key read and the POST are blocked
(`warden.block` events) and `uv run python demo/sink.py --count` stays at 0.
