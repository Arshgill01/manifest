#!/usr/bin/env python3
"""Warden skill entry point: statically audit a third-party Agent Skill and print its
permission card. Self-contained (stdlib only); prefers Manifest's installed `warden`
package when present, else the vendored copy beside this file.

    python scripts/audit.py <skill-dir> [--json] [--no-color]

Exit: 0 ok · 1 review · 2 dangerous · 3 bad usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:  # when run inside the Manifest repo, use the live package
    from warden import card as _card, manifest as _manifest
except ImportError:  # anywhere else, use the vendored copy
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _warden import card as _card, manifest as _manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="warden-audit", description="Audit an Agent Skill before you trust it.")
    ap.add_argument("dir", help="path to the skill directory (must contain SKILL.md)")
    ap.add_argument("--json", action="store_true", help="print the full manifest + findings as JSON")
    ap.add_argument("--no-color", action="store_true", help="disable ANSI color")
    a = ap.parse_args(argv)

    skill_dir = Path(a.dir).expanduser().resolve()
    if not (skill_dir / "SKILL.md").exists():
        print(f"warden: no SKILL.md in {a.dir!r}", file=sys.stderr)
        return 3

    m = _manifest.audit(skill_dir)
    if a.json:
        print(json.dumps(m, indent=2))
    else:
        color = False if a.no_color else _card.use_color()
        footer = None
        if m["verdict"] == "dangerous":
            footer = ["DANGEROUS: do not install this skill.",
                      "If you must inspect it, run it only in a sandbox with no network and no access to secret files."]
        elif m["verdict"] == "review":
            footer = ["REVIEW the findings above before installing."]
        print(_card.render(m, color=color, footer=footer))
    return {"ok": 0, "review": 1, "dangerous": 2}[m["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
