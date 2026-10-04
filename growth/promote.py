"""Promote a finished v2 growth harness: export its grown routines as Agent Skills (and optionally make it the
default harness). Copies teacher-written files verbatim; nothing is edited by hand.

    uv run python -m growth.promote harnesses/<run-id>/registry.json [--set-default] [--dry-run]

For every grown routine in the registry: skills/<name>/{SKILL.md, scripts/routine.py, manifest.json,
proposal.json} from the exact version the registry points at. A skill dir that already exists with a different
provenance (another run) is refused unless --replace. With --set-default, routines/registry.json becomes a copy
of the promoted registry (the hackathon registry is kept as harnesses/hackathon/registry.json).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from harness.log import ROOT


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else ROOT / path


def promote(registry: Path, *, replace: bool = False, dry: bool = False, set_default: bool = False,
            skills_root: Path | None = None) -> list[str]:
    entries = json.loads(registry.read_text())
    done = []
    for e in entries:
        if e.get("source") != "grown":
            continue
        src = _resolve(e["path"])
        prov = json.loads((src / "proposal.json").read_text()) if (src / "proposal.json").exists() else {}
        dest = (skills_root or ROOT / "skills") / e["name"]
        if dest.exists() and not replace:
            old = json.loads((dest / "proposal.json").read_text()) if (dest / "proposal.json").exists() else {}
            if old.get("runId") != prov.get("runId"):
                raise SystemExit(f"skills/{e['name']} exists from another run ({old.get('runId', 'hackathon')}); "
                                 f"pass --replace to overwrite")
        print(f"{'would export' if dry else 'export'} {e['name']}: {src} -> {dest}/")
        if not dry:
            if dest.exists():
                shutil.rmtree(dest)
            (dest / "scripts").mkdir(parents=True)
            shutil.copy2(src / "SKILL.md", dest / "SKILL.md")
            shutil.copy2(src / "routine.py", dest / "scripts" / "routine.py")
            for f in ("manifest.json", "proposal.json"):
                if (src / f).exists():
                    shutil.copy2(src / f, dest / f)
        done.append(e["name"])
    if set_default and not dry:
        hack = ROOT / "harnesses" / "hackathon" / "registry.json"
        if not hack.exists():
            hack.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "routines" / "registry.json", hack)
        shutil.copy2(registry, ROOT / "routines" / "registry.json")
        print(f"routines/registry.json <- {registry.relative_to(ROOT)} (hackathon registry kept at {hack.relative_to(ROOT)})")
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("registry", type=Path)
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--set-default", action="store_true")
    a = ap.parse_args(argv)
    reg = a.registry if a.registry.is_absolute() else (Path.cwd() / a.registry)
    names = promote(reg.resolve(), replace=a.replace, dry=a.dry_run, set_default=a.set_default)
    print(f"{len(names)} routine(s): {', '.join(names) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
