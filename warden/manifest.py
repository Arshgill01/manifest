"""Warden permission manifests (SPEC §6.2).

`build(skill_dir, requested, findings) -> {skill, read, write, commands, network, findings, verdict, ...}`

The manifest is the skill's *footprint*: what it declares it needs (`requested`, or its
`manifest.json`, or the default grown-routine grant) merged with what the static scan saw it
actually do. Anything detected but not declared is listed under `undeclared`. The verdict:

* `dangerous`: any critical finding (credential paths, decode-then-exec, pipe-to-shell), network
  plus reads outside the task dir, or writes to `tests/**` / outside the task dir;
* `review`: any high/medium finding, network, out-of-dir reads, extra commands, or undeclared use;
* `ok`: within the default grant (read `**`, write `src/**`, `python -m pytest`, no network).

Stdlib only (vendored into `skills/warden/scripts/`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .scan import SEVERITIES, scan

DEFAULT_GRANT = {"read": ["**"], "write": ["src/**"], "commands": ["python -m pytest"], "network": False}
SAFE_COMMANDS = ("python -m pytest", "pytest", "python -m py_compile")


# --------------------------------------------------------------------------- SKILL.md

def read_frontmatter(skill_dir: Path) -> dict:
    """Minimal YAML frontmatter reader (flat keys + one nested map such as `metadata`)."""
    p = Path(skill_dir) / "SKILL.md"
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*(\n|$)", text, re.S)
    if not m:
        return {}
    out: dict = {}
    parent = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        key, _, val = line.strip().partition(":")
        val = val.strip().strip("'\"")
        if indent and parent is not None:
            out[parent][key.strip()] = val
        elif val == "":
            parent = key.strip()
            out[parent] = {}
        else:
            parent = None
            out[key.strip()] = val
    return out


def skill_name(skill_dir: Path) -> str:
    return read_frontmatter(skill_dir).get("name") or Path(skill_dir).resolve().name


# --------------------------------------------------------------------------- requested

def normalize_requested(req) -> dict:
    """Accept a dict `{read, write, commands, network}` or a list like
    `["read:src/**", "write:src/**", "command:python -m pytest", "network"]`."""
    if req is None:
        return {}
    if isinstance(req, dict):
        out = {}
        for k in ("read", "write", "commands"):
            v = req.get(k)
            if v is not None:
                out[k] = [v] if isinstance(v, str) else [str(x) for x in v]
        if "network" in req:
            out["network"] = bool(req["network"])
        return out
    out: dict = {"read": [], "write": [], "commands": [], "network": False}
    for item in req:
        s = str(item).strip()
        kind, _, val = s.partition(":")
        kind = kind.strip().lower()
        if kind in ("read", "write"):
            out[kind].append(val.strip())
        elif kind in ("command", "commands", "run", "exec"):
            out["commands"].append(val.strip())
        elif kind.startswith("network") or kind == "net":
            out["network"] = val.strip().lower() not in ("false", "no", "0")
    return {k: v for k, v in out.items() if v not in ([], None)} | {"network": out["network"]}


def declared_permissions(skill_dir: Path, requested=None) -> tuple[dict, str]:
    """(permissions, where they came from)."""
    if requested is not None:
        return {**DEFAULT_GRANT, **normalize_requested(requested)}, "requested"
    mf = Path(skill_dir) / "manifest.json"
    if mf.exists():
        try:
            data = json.loads(mf.read_text())
            return {**DEFAULT_GRANT, **normalize_requested(data.get("requested", data))}, "manifest.json"
        except (json.JSONDecodeError, AttributeError):
            pass
    return dict(DEFAULT_GRANT), "default"


# --------------------------------------------------------------------------- footprint

_QUOTED = re.compile(r"'([^']+)'|\"([^\"]+)\"")


def _outside_glob(detail: str) -> str:
    m = _QUOTED.search(detail)
    path = (m.group(1) or m.group(2)) if m else ""
    if re.search(r"\.ssh|id_rsa|id_ed25519|id_ecdsa", path + " " + detail):
        return "~/.ssh/**"
    if ".aws" in path:
        return "~/.aws/**"
    if path.startswith("~") or "home directory" in detail:
        return "~/**"
    if path:
        return path.rstrip("/") + ("/**" if path.endswith("/") else "")
    return "~/**"


def _detected(findings: list[dict]) -> dict:
    det = {"read": [], "commands": [], "network": False, "hosts": []}
    for f in findings:
        rule, d = f["rule"], f.get("detail", "")
        if rule == "network":
            det["network"] = True
            m = re.search(r"://([^/\s'\"]+)", d)
            if m and m.group(1) not in det["hosts"]:
                det["hosts"].append(m.group(1))
        elif rule in ("secrets-path", "out-of-dir-path"):
            g = _outside_glob(d)
            if g not in det["read"]:
                det["read"].append(g)
        elif rule in ("shell", "subprocess"):
            cmd = d.split(":", 1)[-1].strip()
            if cmd and not cmd.startswith("<") and cmd not in det["commands"]:
                det["commands"].append(" ".join(cmd.split()[:3]))
    return det


def _outside_task(glob: str) -> bool:
    return glob.startswith(("/", "~")) or ".." in Path(glob).parts


def _covers(granted: list[str], cmd: str) -> bool:
    return any(cmd == g or cmd.startswith(g + " ") or g.startswith(cmd) for g in granted)


# --------------------------------------------------------------------------- build

def build(skill_dir: Path, requested, findings: list) -> dict:
    skill_dir = Path(skill_dir)
    declared, source = declared_permissions(skill_dir, requested)
    det = _detected(findings)

    read = list(dict.fromkeys(declared["read"] + det["read"]))
    write = list(dict.fromkeys(declared["write"]))
    commands = list(dict.fromkeys(declared["commands"] +
                                  [c for c in det["commands"] if not _covers(declared["commands"], c)]))
    network = bool(declared["network"] or det["network"])
    undeclared = {
        "read": [g for g in det["read"] if g not in declared["read"]],
        "commands": [c for c in det["commands"] if not _covers(declared["commands"], c)],
        "network": det["network"] and not declared["network"],
    }

    sev = {s: [f for f in findings if f["severity"] == s] for s in SEVERITIES}
    reasons_d, reasons_r = [], []
    for f in sev["critical"]:
        reasons_d.append(f"{f['rule']}: {f['detail']} ({f['file']}:{f['line']})")
    out_reads = [g for g in read if _outside_task(g)]
    if network and out_reads:
        reasons_d.append(f"network access combined with reads outside the task dir ({', '.join(out_reads)})")
    bad_writes = [g for g in write if _outside_task(g) or re.match(r"^\**/?tests?(/|$)", g) or g in ("**", "*")]
    if bad_writes:
        reasons_d.append(f"writes outside src/ ({', '.join(bad_writes)}): may edit tests or your files")
    if undeclared["network"]:
        reasons_r.append("uses the network without declaring it")
    elif network:
        reasons_r.append("requests network access")
    if out_reads and not network:
        reasons_r.append(f"reads outside the task dir ({', '.join(out_reads)})")
    extra = [c for c in commands if not any(c.startswith(s) for s in SAFE_COMMANDS)]
    if extra:
        reasons_r.append(f"runs commands beyond pytest ({', '.join(extra)})")
    for f in sev["high"]:
        reasons_r.append(f"{f['rule']}: {f['detail']} ({f['file']}:{f['line']})")
    if sev["medium"]:
        reasons_r.append(f"{len(sev['medium'])} medium finding(s)")

    verdict = "dangerous" if reasons_d else "review" if reasons_r else "ok"
    return {
        "skill": skill_name(skill_dir),
        "read": read,
        "write": write,
        "commands": commands,
        "network": network,
        "findings": findings,
        "verdict": verdict,
        "reasons": reasons_d + reasons_r,
        "undeclared": undeclared,
        "hosts": det["hosts"],
        "declaredFrom": source,
    }


def granted(manifest: dict) -> dict:
    """What the runtime sandbox should actually allow for this manifest."""
    return {
        "skill": manifest.get("skill"),
        "read": [g for g in manifest.get("read", []) if not _outside_task(g)] or ["**"],
        "write": [g for g in manifest.get("write", []) if not _outside_task(g)
                  and not re.match(r"^\**/?tests?(/|$)", g)] or [],
        "commands": manifest.get("commands", []),
        "network": bool(manifest.get("network")) and manifest.get("verdict") != "dangerous",
        "verdict": manifest.get("verdict"),
    }


def audit(skill_dir: Path, requested=None, teacher=None, log=None) -> dict:
    """scan + build, and emit `warden.manifest` when given an EventLog."""
    findings = scan(Path(skill_dir), teacher=teacher)
    m = build(Path(skill_dir), requested, findings)
    if log is not None:
        emit(log, m)
    return m


def emit(log, m: dict) -> dict:
    return log.emit("warden.manifest", skill=m["skill"], read=m["read"], write=m["write"],
                    commands=m["commands"], network=m["network"], findings=m["findings"],
                    verdict=m["verdict"], reasons=m.get("reasons", []), undeclared=m.get("undeclared"))
