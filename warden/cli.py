"""`manifest` CLI (pyproject entry point `warden.cli:main`).

    manifest warden audit <skill-dir>          # scan + bordered permission card + verdict
    manifest skill add <skill-dir>             # audit, then install iff not dangerous
    manifest skill add <skill-dir> --force-run # install/run even if dangerous, under the sandbox

Exit codes: 0 ok/installed · 1 blocked by verdict · 2 bad usage · 3 runtime block occurred.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import manifest as wm
from .card import render, use_color

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"


def _load_log(label: str):
    try:
        from harness.log import EventLog
        return EventLog.create(label)
    except Exception:
        return None


def _load_teacher(enabled: bool):
    if not enabled:
        return None
    try:
        from harness.teacher import Teacher
        return Teacher(_load_log("warden-teacher"))
    except Exception as e:
        print(f"warden: teacher pass unavailable ({type(e).__name__}); static scan only", file=sys.stderr)
        return None


def _resolve(skill_dir: str) -> Path:
    p = Path(skill_dir).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p)
    if not (p / "SKILL.md").exists():
        print(f"warden: no SKILL.md in {skill_dir!r}", file=sys.stderr)
        raise SystemExit(2)
    return p.resolve()


def _audit(skill_dir: Path, *, teacher=False, log=None) -> dict:
    return wm.audit(skill_dir, teacher=_load_teacher(teacher), log=log)


def _print_card(m: dict, footer=None, as_json=False) -> None:
    if as_json:
        print(json.dumps({k: v for k, v in m.items()}, indent=2))
    else:
        print(render(m, color=use_color(), footer=footer))


def cmd_warden_audit(args) -> int:
    skill_dir = _resolve(args.dir)
    log = _load_log("warden-audit")
    m = _audit(skill_dir, teacher=args.teacher, log=log)
    footer = None
    if m["verdict"] == "dangerous":
        footer = ["Blocked. To run it anyway under the sandbox:",
                  f"  manifest skill add {args.dir} --force-run"]
    _print_card(m, footer=footer, as_json=args.json)
    return {"ok": 0, "review": 0, "dangerous": 1}[m["verdict"]]


def cmd_skill_add(args) -> int:
    skill_dir = _resolve(args.dir)
    log = _load_log("warden-install")
    m = _audit(skill_dir, teacher=args.teacher, log=log)
    _print_card(m, as_json=args.json)

    dangerous = m["verdict"] == "dangerous"
    if dangerous and not args.force_run:
        print(_hr("REFUSED: verdict is DANGEROUS. Not installed. Re-run with --force-run to "
                  "execute it under Warden's sandbox (it will still be blocked at runtime)."))
        return 1

    if dangerous and args.force_run:
        print(_hr("--force-run: executing under Warden's sandbox (manifest permissions enforced)."))
        rc = _force_run(skill_dir, m, log)
        return rc

    # ok / review → install
    dest = _install(skill_dir, m)
    print(_hr(f"Installed to {dest.relative_to(ROOT) if dest.is_relative_to(ROOT) else dest} "
              f"with manifest (verdict: {m['verdict']})."))
    return 0


def _force_run(skill_dir: Path, m: dict, log) -> int:
    """Run the skill's declared script under SandboxExecutor; report whether anything was blocked."""
    from .sandbox import SandboxExecutor

    script = _entry_script(skill_dir)
    if script is None:
        print(_hr("No runnable script found (looked for scripts/*.py). Nothing executed."), file=sys.stderr)
        return 2
    grant = wm.granted(m)
    executor = SandboxExecutor(log)
    print(f"  running: {script.relative_to(skill_dir)}   (enforcement: {executor.mode})")
    res = executor.run_script(script, grant, _workdir(), skill=m["skill"])
    blocks = res.get("blocks") or []
    out = (res.get("stderr") or "").strip()
    if out:
        print("  --- script output (stderr) ---")
        for line in out.splitlines()[-12:]:
            print("  " + line)
    if blocks:
        print(_hr(f"Warden blocked {len(blocks)} dangerous operation(s):"))
        for b in blocks:
            print(f"    ✗ {b['attempted']}  —  {b['reason']}")
        print("  The skill ran but could touch nothing it shouldn't. Logged as warden.block.")
        return 3
    print(_hr("Script ran inside the sandbox; no blocked operations were attempted."))
    return 0


def _entry_script(skill_dir: Path) -> Path | None:
    scripts = skill_dir / "scripts"
    if scripts.is_dir():
        pys = sorted(scripts.glob("*.py"))
        for name in ("quick_fix.py", "run.py", "main.py", "audit.py", "routine.py"):
            hit = scripts / name
            if hit in pys:
                return hit
        if pys:
            return pys[0]
    return None


def _workdir() -> Path:
    """A disposable task-like workdir so a force-run has a plausible place to look."""
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="warden-forcerun-"))
    (d / "src").mkdir()
    (d / "tests").mkdir()
    (d / "src" / "sample.py").write_text("def add(a, b):\n    return a + b\n")
    (d / "tests" / "test_sample.py").write_text(
        "from src.sample import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    return d


def _install(skill_dir: Path, m: dict) -> Path:
    SKILLS_DIR.mkdir(exist_ok=True)
    dest = SKILLS_DIR / m["skill"]
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(skill_dir, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (dest / "manifest.json").write_text(json.dumps(wm.granted(m), indent=2) + "\n")
    return dest


def _hr(text: str) -> str:
    return "\n" + text + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="manifest", description="Manifest — Warden CLI")
    p.add_argument("--version", action="version", version="manifest-warden 0.1.0")
    sub = p.add_subparsers(dest="group", required=True)

    warden = sub.add_parser("warden", help="Warden commands").add_subparsers(dest="cmd", required=True)
    a = warden.add_parser("audit", help="scan a skill and print its permission card")
    a.add_argument("dir")
    a.add_argument("--teacher", action="store_true", help="add the teacher deobfuscation pass")
    a.add_argument("--json", action="store_true", help="print the manifest as JSON")
    a.set_defaults(func=cmd_warden_audit)

    skill = sub.add_parser("skill", help="install Agent Skills").add_subparsers(dest="cmd", required=True)
    s = skill.add_parser("add", help="audit then install a skill")
    s.add_argument("dir")
    s.add_argument("--force-run", action="store_true",
                   help="run even if DANGEROUS, under the sandbox (operations still blocked)")
    s.add_argument("--teacher", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_skill_add)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2


if __name__ == "__main__":
    sys.exit(main())
