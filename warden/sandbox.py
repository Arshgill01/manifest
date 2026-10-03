"""Runtime enforcement: run routines and skill scripts under macOS `sandbox-exec` (SPEC §6.3).

The untrusted code (a grown routine or a third-party skill script) runs in a child Python
process wrapped in a Seatbelt profile generated from its Warden manifest:

* network: denied, except the student endpoint `localhost:11434` (and broader outbound only
  when the manifest grants `network: true` and the verdict is not `dangerous`);
* file reads: system paths Python needs + the interpreter/venv + `harness/` `warden/`
  `routines/` + the routine dir + the manifest's read globs inside the workdir;
* file writes: the manifest's write globs inside the workdir (never `tests/**`) + a private TMPDIR;
* process-exec: only the Python interpreter (plus the first token of each granted command);
* `HOME` = `demo/fakehome`; its `.ssh/` and the repo `.env` are explicitly denied.

Globs outside the workdir (`~/.ssh/**`, `/Users/...`) are never granted at runtime, whatever
the manifest says: Warden's job is to describe them on the card, the sandbox's job is to say no.

Tool and student calls made by a routine are proxied back to the parent over a JSON-lines pipe,
so the parent's `Tools` (manifest-checked) and `EventLog` (single writer) stay authoritative.
A Python audit hook in the child reports attempted violations so the parent can log
`warden.block`; the kernel sandbox is what actually denies them. Where `sandbox-exec` is not
available, the same audit hook *enforces* instead (weaker; reported as `fallback`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FAKEHOME = ROOT / "demo" / "fakehome"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
OLLAMA_PORT = 11434

DEFAULT_MANIFEST = {
    "read": ["**"],
    "write": ["src/**"],
    "commands": ["python -m pytest"],
    "network": False,
}

# Read-only system locations a Python child legitimately needs.
SYSTEM_READ = [
    "/usr", "/System", "/Library/Apple", "/Library/Preferences/Logging",
    "/private/etc", "/private/var/db/timezone", "/private/var/db/dyld", "/dev",
]
DEV_WRITE = ["/dev/null", "/dev/tty", "/dev/stdout", "/dev/stderr", "/dev/dtracehelper"]

# Tool/student methods a sandboxed routine may call through the proxy.
TOOL_METHODS = {"list_files", "read_file", "run_tests", "edit_file", "bash"}
STUDENT_METHODS = {"ask", "chat"}


class SandboxError(RuntimeError):
    """The sandboxed child failed (exception in routine code, timeout, or protocol error)."""


def sandbox_available() -> bool:
    if sys.platform != "darwin" or not os.path.exists(SANDBOX_EXEC):
        return False
    try:
        r = subprocess.run([SANDBOX_EXEC, "-p", "(version 1)(allow default)", "/usr/bin/true"],
                           capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


# --------------------------------------------------------------------------- policy

def _real(p: str | Path) -> str:
    return os.path.realpath(os.path.expanduser(str(p)))


def _glob_to_regex(glob: str) -> str:
    """`src/**` -> `src(/.*)?`, `src/*.py` -> `src/[^/]*\\.py` (relative, unanchored)."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(.*/)?"); i += 3
        elif glob.startswith("/**", i) and i + 3 == len(glob):
            out.append("(/.*)?"); i += 3
        elif glob.startswith("**", i):
            out.append(".*"); i += 2
        elif glob[i] == "*":
            out.append("[^/]*"); i += 1
        elif glob[i] == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(glob[i])); i += 1
    return "".join(out)


def _workdir_rules(globs: list[str], workdir: str) -> tuple[list[str], list[str], list[str]]:
    """Split manifest globs into (subpaths, anchored regexes, rejected) relative to workdir."""
    subpaths, regexes, rejected = [], [], []
    for g in globs or []:
        g = g.strip()
        if not g:
            continue
        if g.startswith(("/", "~")) or ".." in Path(g).parts:
            rejected.append(g)
            continue
        g = g.lstrip("./") if g.startswith("./") else g
        if g in ("**", "*", "."):
            subpaths.append(workdir)
        elif g.endswith("/**") and not any(c in g[:-3] for c in "*?["):
            subpaths.append(os.path.join(workdir, g[:-3]))
        elif not any(c in g for c in "*?["):
            subpaths.append(os.path.join(workdir, g))
        else:
            regexes.append("^" + re.escape(workdir) + "/" + _glob_to_regex(g) + "$")
    return subpaths, regexes, rejected


def python_read_roots() -> list[str]:
    roots = {sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.dirname(_real(sys.executable))}
    roots |= {os.path.dirname(os.path.dirname(_real(sys.executable)))}
    for p in sys.path:
        if p and "site-packages" in p:
            roots.add(p)
    return sorted(_real(r) for r in roots if r)


def build_policy(manifest: dict | None, workdir: Path, *, extra_read: list[Path] = (),
                 tmpdir: Path | None = None) -> dict:
    """Everything the profile and the child's audit hook need, as plain JSON."""
    m = {**DEFAULT_MANIFEST, **(manifest or {})}
    wd = _real(workdir)
    r_sub, r_re, r_rej = _workdir_rules(m.get("read"), wd)
    w_sub, w_re, w_rej = _workdir_rules(m.get("write"), wd)
    code_roots = [_real(ROOT / d) for d in ("harness", "warden", "routines")]
    network_open = bool(m.get("network")) and m.get("verdict") != "dangerous"
    exec_allow = sorted({_real(sys.executable), sys.executable, "/usr/bin/true"} |
                        _command_binaries(m.get("commands") or []))
    deny = [_real(FAKEHOME / ".ssh"), _real(ROOT / ".env"), _real(Path.home() / ".ssh")]
    return {
        "workdir": wd,
        "read_subpaths": sorted(set(SYSTEM_READ + python_read_roots() + code_roots + r_sub +
                                    [_real(p) for p in extra_read] + ([_real(tmpdir)] if tmpdir else []))),
        "read_regex": r_re,
        "read_literals": [_real(ROOT)],  # directory listing only, so `import warden` resolves
        "write_subpaths": sorted(set(w_sub + ([_real(tmpdir)] if tmpdir else []))),
        "write_regex": w_re,
        "write_literals": DEV_WRITE,
        "deny_read": deny,
        "deny_write": [os.path.join(wd, "tests")] + deny,
        "exec_allow": exec_allow,
        "network_open": network_open,
        "allowed_ports": [OLLAMA_PORT],
        "rejected_globs": sorted(set(r_rej + w_rej)),
    }


def _command_binaries(commands: list[str]) -> set[str]:
    out = set()
    for c in commands:
        first = c.split()[0] if c.split() else ""
        if first in ("python", "python3", "pytest"):
            continue  # runs through the interpreter we already allow
        hit = shutil.which(first)
        if hit:
            out |= {hit, _real(hit)}
    return out


def _q(s: str) -> str:
    return json.dumps(s)  # SBPL string literal == JSON string for our paths


def render_profile(policy: dict) -> str:
    """Seatbelt (SBPL) profile text. Later rules win, so the denies come last."""
    L = [
        "(version 1)",
        "(deny default)",
        "(allow process-fork)",
        "(allow process-exec " + " ".join(f"(literal {_q(p)})" for p in policy["exec_allow"]) + ")",
        "(allow signal (target same-sandbox))",
        "(allow sysctl-read)",
        '(allow mach-lookup (global-name "com.apple.system.opendirectoryd.libinfo" '
        '"com.apple.system.logger" "com.apple.system.notification_center"))',
        "(allow ipc-posix-shm-read-data ipc-posix-shm-read-metadata)",
        "(allow file-read-metadata)",
        '(allow file-read* (literal "/") (literal "/private") (literal "/private/var"))',
        "(allow file-read*",
        *[f"  (subpath {_q(p)})" for p in policy["read_subpaths"]],
        *[f"  (regex {_q(r)})" for r in policy["read_regex"]],
        *[f"  (literal {_q(p)})" for p in policy["read_literals"]],
        ")",
        "(allow file-write*",
        *[f"  (subpath {_q(p)})" for p in policy["write_subpaths"]],
        *[f"  (regex {_q(r)})" for r in policy["write_regex"]],
        *[f"  (literal {_q(p)})" for p in policy["write_literals"]],
        '  (regex #"^/dev/fd/")',
        ")",
        "(deny file-read* " + " ".join(f"(subpath {_q(p)})" for p in policy["deny_read"]) + ")",
        "(deny file-write* " + " ".join(f"(subpath {_q(p)})" for p in policy["deny_write"]) + ")",
        "(deny network*)",
    ]
    if policy["network_open"]:
        L.append("(allow network-outbound)")
        L.append('(allow mach-lookup (global-name "com.apple.dnssd.service"))')
    for port in policy["allowed_ports"]:
        L.append(f'(allow network-outbound (remote ip "localhost:{port}"))')
    return "\n".join(L) + "\n"


def child_env(tmpdir: Path) -> dict:
    env = {
        "HOME": str(FAKEHOME),
        "TMPDIR": str(tmpdir),
        "PATH": os.pathsep.join([os.path.dirname(sys.executable), "/usr/bin", "/bin"]),
        "PYTHONPATH": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
    }
    for k in ("OLLAMA_HOST", "STUDENT_MODEL"):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


def wrap_command(argv: list[str], manifest: dict | None, workdir: Path, *,
                 tmpdir: Path | None = None) -> tuple[list[str], dict]:
    """Wrap any argv (e.g. `python -m pytest`) in the manifest's sandbox. Returns (argv, env).

    For the harness tool layer (defense in depth): `subprocess.run(*wrap_command(...))`.
    Falls back to the bare argv (with HOME=fakehome) when sandbox-exec is unavailable.
    """
    tmpdir = Path(tmpdir or tempfile.mkdtemp(prefix="warden-"))
    policy = build_policy(manifest, workdir, tmpdir=tmpdir)
    env = child_env(tmpdir)
    if not sandbox_available():
        return list(argv), env
    if argv and os.path.basename(argv[0]).startswith("python"):
        argv = [sys.executable, *argv[1:]]
    return [SANDBOX_EXEC, "-p", render_profile(policy), *argv], env


# --------------------------------------------------------------------------- executor

def _state_to_json(state: Any) -> dict:
    if hasattr(state, "model_dump"):
        return state.model_dump(mode="json")
    if isinstance(state, dict):
        return state
    return dict(vars(state))


def _state_from_json(template: Any, data: dict) -> Any:
    if hasattr(type(template), "model_validate"):
        return type(template).model_validate(data)
    if isinstance(template, dict):
        return data
    for k, v in data.items():
        setattr(template, k, v)
    return template


def _model_from_schema(schema: dict):
    """Rebuild a (flat) pydantic model from a child's JSON schema so the parent can call student.ask."""
    from pydantic import create_model

    tmap = {"string": str, "integer": int, "number": float, "boolean": bool, "array": list, "object": dict}
    required = set(schema.get("required", []))
    fields = {}
    for name, spec in (schema.get("properties") or {}).items():
        t = spec.get("type")
        if t is None and "anyOf" in spec:
            t = next((s.get("type") for s in spec["anyOf"] if s.get("type") != "null"), None)
        py = tmap.get(t, Any)
        fields[name] = (py, ...) if name in required else (py | None, None)
    return create_model(schema.get("title") or "Schema", **fields)


class SandboxExecutor:
    """Executor (CONTRACT 2.4) that runs routine code under sandbox-exec.

    `run(routine_dir, state, tools, student, manifest) -> State`
    `run_script(script, manifest, workdir, args=()) -> dict` (third-party skill scripts)
    """

    def __init__(self, log=None, *, timeout: float = 120.0, enforce: str = "auto"):
        self.log = log
        self.timeout = timeout
        self.mode = "sandbox" if enforce in ("auto", "sandbox") and sandbox_available() else "fallback"
        if enforce == "sandbox" and self.mode != "sandbox":
            raise SandboxError("sandbox-exec is not available on this machine")

    # -- public ------------------------------------------------------------------
    def run(self, routine_dir: Path, state: Any, tools: Any, student: Any, manifest: dict | None) -> Any:
        routine_dir = Path(routine_dir)
        sj = _state_to_json(state)
        workdir = Path(sj.get("task_dir") or getattr(tools, "workdir", None) or os.getcwd())
        skill = (manifest or {}).get("skill") or routine_dir.name
        job = {"kind": "routine", "routine": str(routine_dir / "routine.py"), "state": sj}
        res = self._spawn(job, skill=skill, manifest=manifest, workdir=workdir,
                          extra_read=[routine_dir], tools=tools, student=student)
        if res["status"] != "done":
            raise SandboxError(f"routine {skill!r} failed in sandbox: {res.get('error', '')[-2000:]}"
                              f"\n--- stderr ---\n{res.get('stderr', '')[-1500:]}")
        return _state_from_json(state, res["state"])

    def run_script(self, script: Path, manifest: dict | None, workdir: Path,
                   args: list[str] = (), *, skill: str | None = None) -> dict:
        """Run a skill script (`.py` or `.sh`) under the sandbox. Never raises on script failure."""
        script = Path(script).resolve()
        skill = skill or (manifest or {}).get("skill") or script.parent.parent.name
        job = {"kind": "script", "script": str(script), "args": list(args)}
        return self._spawn(job, skill=skill, manifest=manifest, workdir=Path(workdir),
                           extra_read=[script.parent.parent], tools=None, student=None)

    # -- internals ---------------------------------------------------------------
    def _block(self, skill: str, attempted: str, reason: str) -> None:
        if self.log is not None:
            self.log.emit("warden.block", skill=skill, attempted=attempted, reason=reason,
                          enforcement=self.mode)

    def _spawn(self, job: dict, *, skill: str, manifest: dict | None, workdir: Path,
               extra_read: list[Path], tools: Any, student: Any) -> dict:
        tmp = Path(tempfile.mkdtemp(prefix="warden-"))
        policy = build_policy(manifest, workdir, extra_read=extra_read, tmpdir=tmp)
        job = {**job, "policy": policy, "enforce": self.mode == "fallback", "skill": skill}
        argv = [sys.executable, "-I", "-B", "-c",
                "import sys; sys.path.insert(0, %r); from warden import _child; _child.main()" % str(ROOT)]
        if self.mode == "sandbox":
            argv = [SANDBOX_EXEC, "-p", render_profile(policy), *argv]
        proc = subprocess.Popen(argv, cwd=policy["workdir"], env=child_env(tmp), text=True,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                bufsize=1)
        stderr: list[str] = []
        t = threading.Thread(target=lambda: stderr.extend(proc.stderr), daemon=True)
        t.start()
        timer = threading.Timer(self.timeout, proc.kill)
        timer.start()
        blocks: list[dict] = []
        result: dict = {"status": "error", "error": "child exited without a result"}
        try:
            proc.stdin.write(json.dumps(job) + "\n"); proc.stdin.flush()
            for line in proc.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                op = msg.get("op")
                if op == "block":
                    blocks.append(msg)
                    self._block(skill, msg["attempted"], msg["reason"])
                elif op == "call":
                    reply = self._dispatch(msg, tools, student)
                    proc.stdin.write(json.dumps(reply, default=str) + "\n"); proc.stdin.flush()
                elif op in ("done", "error", "exit"):
                    result = {k: v for k, v in msg.items() if k != "op"}
                    result["status"] = op
                    break
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            timer.cancel()
            t.join(timeout=1)
            shutil.rmtree(tmp, ignore_errors=True)
        if proc.returncode is not None and proc.returncode < 0 and result["status"] == "error":
            result["error"] = f"killed after {self.timeout:.0f}s timeout"
        err_text = "".join(stderr)
        result["stderr"] = err_text[-4000:]
        result["blocks"] = blocks
        result["enforcement"] = self.mode
        # The kernel may deny something the audit hook did not attribute (e.g. via ctypes).
        if not blocks and "Operation not permitted" in (err_text + str(result.get("error", ""))):
            self._block(skill, "unattributed operation", "sandbox-exec denied it (EPERM)")
            result["blocks"] = [{"attempted": "unattributed operation", "reason": "EPERM"}]
        return result

    def _dispatch(self, msg: dict, tools: Any, student: Any) -> dict:
        target, method = msg.get("target"), msg.get("method")
        args, kwargs = msg.get("args") or [], msg.get("kwargs") or {}
        try:
            if target == "tools" and method in TOOL_METHODS and tools is not None:
                return {"ok": True, "result": getattr(tools, method)(*args, **kwargs)}
            if target == "student" and method in STUDENT_METHODS and student is not None:
                if method == "ask":
                    schema = kwargs.pop("schema", None)
                    if schema is None and len(args) >= 3:
                        args, schema = list(args[:2]), args[2]
                    if isinstance(schema, dict):
                        kwargs["schema"] = _model_from_schema(schema)
                out = getattr(student, method)(*args, **kwargs)
                if hasattr(out, "model_dump"):
                    out = out.model_dump(mode="json")
                return {"ok": True, "result": out}
            return {"ok": False, "type": "PermissionError", "error": f"{target}.{method} is not proxied"}
        except Exception as e:  # surface to the routine as an exception of the same name
            return {"ok": False, "type": type(e).__name__, "error": str(e)}


# --------------------------------------------------------------------------- self-test

def selftest(verbose: bool = True) -> dict:
    """Prove the profile: blocks ~/.ssh + outbound network; allows python, pytest, src/** writes, Ollama."""
    probe = r'''
import json, os, socket, subprocess, sys, urllib.request
home = os.path.expanduser("~")
res = {}
def t(name, fn):
    try:
        fn(); res[name] = "allowed"
    except Exception as e:
        res[name] = "blocked: " + type(e).__name__
t("read ~/.ssh/id_ed25519", lambda: open(os.path.join(home, ".ssh", "id_ed25519")).read())
t("read real ~/.ssh", lambda: os.listdir(os.environ["REAL_SSH"]))
t("read repo .env", lambda: open(os.environ["REPO_ENV"]).read())
t("read workdir", lambda: open("src/mod.py").read())
t("write src/**", lambda: open("src/new.py", "w").write("x = 1\n"))
t("write tests/**", lambda: open("tests/evil.py", "w").write("x = 1\n"))
t("connect 1.1.1.1:443", lambda: socket.create_connection(("1.1.1.1", 443), timeout=3).close())
t("connect localhost:8765 (sink)", lambda: socket.create_connection(("127.0.0.1", 8765), timeout=3).close())
def ollama():
    try:
        socket.create_connection(("127.0.0.1", 11434), timeout=3).close()
    except ConnectionRefusedError:
        pass  # sandbox allowed the connect; Ollama just isn't running
t("connect localhost:11434 (ollama)", ollama)
t("run pytest", lambda: subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                        check=True, capture_output=True))
t("exec curl", lambda: subprocess.run(["/usr/bin/curl", "-s", "https://example.com"], check=True, capture_output=True))
print(json.dumps(res))
'''
    expect = {
        "read ~/.ssh/id_ed25519": "blocked", "read real ~/.ssh": "blocked", "read repo .env": "blocked",
        "read workdir": "allowed", "write src/**": "allowed", "write tests/**": "blocked",
        "connect 1.1.1.1:443": "blocked", "connect localhost:8765 (sink)": "blocked",
        "connect localhost:11434 (ollama)": "allowed", "run pytest": "allowed", "exec curl": "blocked",
    }
    with tempfile.TemporaryDirectory(prefix="warden-selftest-") as d:
        wd = Path(d) / "work"
        (wd / "src").mkdir(parents=True); (wd / "tests").mkdir()
        (wd / "src" / "mod.py").write_text("def add(a, b):\n    return a + b\n")
        (wd / "tests" / "test_mod.py").write_text(
            "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent.parent / 'src'))\n"
            "from mod import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
        (wd / "probe.py").write_text(probe)
        argv, env = wrap_command(["python", "probe.py"], None, wd, tmpdir=Path(d) / "tmp")
        (Path(d) / "tmp").mkdir()
        env.update(REAL_SSH=str(Path.home() / ".ssh"), REPO_ENV=str(ROOT / ".env"))
        r = subprocess.run(argv, cwd=wd, env=env, capture_output=True, text=True, timeout=120)
        try:
            got = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            raise SandboxError(f"probe failed: {r.stderr[-2000:]}")
    ok = all(got.get(k, "").startswith(v) for k, v in expect.items())
    if verbose:
        print(f"sandbox-exec available: {sandbox_available()}")
        for k, v in expect.items():
            mark = "ok " if got.get(k, "").startswith(v) else "BAD"
            print(f"  [{mark}] {k:<34} expected {v:<8} got {got.get(k)}")
        print("PASS" if ok else "FAIL")
    return {"ok": ok, "results": got, "expected": expect}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Warden sandbox utilities")
    ap.add_argument("--selftest", action="store_true", help="prove the profile blocks/allows what it should")
    ap.add_argument("--profile", metavar="WORKDIR", help="print the default profile for WORKDIR")
    a = ap.parse_args()
    if a.profile:
        print(render_profile(build_policy(None, Path(a.profile))))
    else:
        sys.exit(0 if selftest()["ok"] else 1)
