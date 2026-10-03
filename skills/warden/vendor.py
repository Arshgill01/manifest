"""Copy the stdlib-only Warden modules into skills/warden/scripts/_warden/ so the skill is
self-contained (runs in Claude Code, Codex, anywhere). Run from the repo root."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "warden"
DEST = ROOT / "skills" / "warden" / "scripts" / "_warden"
MODULES = ["scan", "manifest", "card"]
HEADER = "# VENDORED from manifest warden/ — do not edit here. Regenerate: python skills/warden/vendor.py\n"


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for name in MODULES:
        text = (SRC / f"{name}.py").read_text()
        (DEST / f"{name}.py").write_text(HEADER + text)
        print(f"vendored {name}.py")


if __name__ == "__main__":
    main()
