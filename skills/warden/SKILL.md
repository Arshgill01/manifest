---
name: warden
description: Audit a third-party Agent Skill before you install or run it. Use this whenever you are about to install, add, or execute a skill from a marketplace, a teammate, the internet, or any source you do not fully trust — especially one that ships scripts, asks to run commands, or claims it will "fix" or "scan" your project. It statically scans the skill, builds a least-privilege permission manifest (what it reads, writes, runs, and whether it uses the network), and returns an ok / review / dangerous verdict with the exact findings, so you never run untrusted skill code blind.
license: MIT
metadata:
  project: manifest
  homepage: https://github.com/Arshgill01/manifest
---

# Warden — audit a skill before you trust it

Agent Skills can ship arbitrary scripts and tell the agent to run them. **Warden audits a skill
before you install or execute it.** It never runs the skill's own code; it reads it.

## When to use

- Before installing or adding any skill you did not write (a marketplace, a teammate, a gist, the web).
- Before running a script a skill asks you to run ("run `scripts/x.py` first").
- Whenever a skill claims it will "fix", "scan", "optimize", or "clean up" your project and ships code to do it.

## How to run it

```bash
python scripts/audit.py <path-to-skill-dir>
```

It prints a bordered **permission card** and exits:

- `0` — **ok**: stays within a least-privilege default (reads the project, writes only `src/**`,
  runs only `pytest`, no network). Safe to install.
- `1` — **review**: wants more than the default (network, commands beyond pytest, reads outside the
  project). Read the findings before deciding.
- `2` — **dangerous**: reads credential files, hides code in encoded blobs, pipes
  downloads into a shell, exfiltrates over the network, or edits your tests. **Do not install.**

Add `--json` for machine-readable output (the full manifest and every finding).

## What it checks

- **Network**: imports/calls to `socket`, `urllib`, `requests`, `http`, …; `curl`/`wget`/`nc` in
  scripts; URL literals.
- **Credentials & escape**: paths to SSH/AWS keys, `.env`, keychains; any path outside the
  project directory (`~`, `/Users`, `..`).
- **Obfuscation**: base64/hex blobs are decoded and re-scanned, so `exec(b64decode(...))` is judged
  by what it actually does.
- **Shell & exec**: `subprocess(shell=True)`, `os.system`, `eval`/`exec`, pipe-to-shell.
- **Prompt injection**: SKILL.md text that pressures the agent to conceal its actions from you.

The verdict compares what the skill *declares* (its `manifest.json`, if any) against what the scan
*found it do*; anything it does without declaring is flagged as UNDECLARED.

> Part of [Manifest](https://github.com/Arshgill01/manifest). The same engine gates every routine
> the harness grows and sandboxes it at runtime (`manifest skill add --force-run`).
