"""Environment + provenance shared by every entry point.

    load_env()      .env -> os.environ (never overrides what the shell already set)
    host_info()     what produced a run: machine, CPU, RAM, Ollama version, student model digest, options
    config_key(..)  short hash of everything that changes a result, for caches

Every run.start event carries host_info(), so a number in RESULTS.md can always be traced back to the
hardware and settings that produced it (the hackathon numbers came from an M1 laptop; v2 runs from a
CPU-only cloud VM, roughly 6x slower per student call).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# files whose content changes what a harness does at run time (cache keys hash them)
HARNESS_CODE = ["harness/loop.py", "harness/tools.py", "harness/student.py", "harness/controller.py",
                "harness/state.py", "harness/run.py", "growth/eval.py"]


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is a declared dependency
        return
    load_dotenv(ROOT / ".env", override=False)


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _ram_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                return round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3, 1)
    except (ValueError, OSError, AttributeError):
        return None


@lru_cache(maxsize=1)
def _ollama() -> dict:
    """Ollama server version + the student model's digest/quantisation (best effort, never raises)."""
    import urllib.request

    host = (os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    model = os.environ.get("STUDENT_MODEL") or "qwen3.5:4b"
    out: dict = {}
    try:
        with urllib.request.urlopen(f"{host}/api/version", timeout=2) as r:
            out["ollamaVersion"] = json.load(r).get("version")
        with urllib.request.urlopen(f"{host}/api/tags", timeout=2) as r:
            for m in json.load(r).get("models", []):
                if m.get("name") == model or m.get("model") == model:
                    out["modelDigest"] = (m.get("digest") or "")[:12]
                    det = m.get("details") or {}
                    out["quantization"] = det.get("quantization_level")
                    out["parameterSize"] = det.get("parameter_size")
    except Exception:
        pass
    return out


def host_info() -> dict:
    from harness.student import HTTP_TIMEOUT, OPTIONS

    return {
        "hostname": socket.gethostname(),
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "cpu": _cpu_model(),
        "cpus": os.cpu_count(),
        "ramGb": _ram_gb(),
        "python": platform.python_version(),
        "studentModel": os.environ.get("STUDENT_MODEL") or "qwen3.5:4b",
        "studentOptions": dict(OPTIONS),
        "studentHttpTimeout": HTTP_TIMEOUT,
        "codeHash": code_hash(),
        **_ollama(),
    }


def code_hash(paths: list[str] = HARNESS_CODE) -> str:
    h = hashlib.sha256()
    for rel in paths:
        p = ROOT / rel
        if p.exists():
            h.update(rel.encode() + b"\0" + p.read_bytes())
    return h.hexdigest()[:10]


# Bump when the baseline tool loop / tools / student call behaviour changes in a way that changes results.
# (Code hashes go into run.start for provenance, but not into cache keys: unrelated edits must not throw away
# hours of CPU-bound baseline runs.)
BASELINE_VERSION = 3   # 1 = hackathon (M1, 240 s); 2 = v2 protocol (step/call budget, 1800 s cap);
                       # 3 = + tool-argument synonyms (`command` for `cmd`, ...) and errors that name the expected argument


def config_key(**parts) -> str:
    """Hash of the settings that make two runs comparable (model, options, budget, host, baseline version)."""
    info = host_info()
    blob = {
        "model": info["studentModel"], "digest": info.get("modelDigest"), "options": info["studentOptions"],
        "host": info["hostname"], "baselineVersion": BASELINE_VERSION, **parts,
    }
    return hashlib.sha256(json.dumps(blob, sort_keys=True, default=str).encode()).hexdigest()[:10]
