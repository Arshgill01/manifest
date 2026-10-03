"""Child side of SandboxExecutor. Runs inside sandbox-exec; talks JSON lines to the parent.

stdin  <- job, then replies to proxied calls
stdout -> {"op":"call"|"block"|"done"|"error"|"exit", ...}  (routine prints go to stderr)

The audit hook *reports* attempted violations (the kernel sandbox denies them); in fallback
mode (no sandbox-exec) it also *raises* PermissionError, so enforcement still happens in-process.
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from typing import Any

_rpc_out = None
_rpc_in = None
_policy: dict = {}
_enforce = False
_seen: set[tuple[str, str]] = set()
_busy = False


def _send(msg: dict) -> None:
    _rpc_out.write(json.dumps(msg, default=str) + "\n")
    _rpc_out.flush()


def _under(path: str, roots: list[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def _readable(path: str) -> bool:
    if _under(path, _policy["deny_read"]):
        return False
    if path in _policy.get("read_literals", []):
        return True
    return _under(path, _policy["read_subpaths"]) or any(re.match(r, path) for r in _policy["read_regex"])


def _writable(path: str) -> bool:
    if _under(path, _policy["deny_write"]):
        return False
    if path in _policy["write_literals"] or path.startswith("/dev/fd/"):
        return True
    return _under(path, _policy["write_subpaths"]) or any(re.match(r, path) for r in _policy["write_regex"])


def _violation(attempted: str, reason: str) -> None:
    key = (attempted, reason)
    if key not in _seen:
        _seen.add(key)
        _send({"op": "block", "attempted": attempted, "reason": reason})
    if _enforce:
        raise PermissionError(f"warden: {reason}: {attempted}")


def _check_open(path: Any, mode: Any, flags: Any) -> None:
    if not isinstance(path, (str, bytes, os.PathLike)) or isinstance(path, int):
        return
    p = os.path.realpath(os.fsdecode(path))
    if "__pycache__" in p:
        return
    write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
            (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND))
    if write:
        if not _writable(p):
            _violation(f"write {p}", "write outside manifest write globs")
    elif not _readable(p):
        reason = "read of a secret path" if ("/.ssh" in p or p.endswith("/.env")) else "read outside manifest read globs"
        _violation(f"read {p}", reason)


def _check_connect(address: Any) -> None:
    if isinstance(address, tuple) and len(address) >= 2:
        host, port = str(address[0]), address[1]
        local = host in ("127.0.0.1", "::1", "localhost")
        if _policy["network_open"] and not local:
            return
        if not (local and port in _policy["allowed_ports"]):
            _violation(f"connect {host}:{port}", "network denied by manifest (network: false)")
    elif isinstance(address, (str, bytes)):
        _violation(f"connect unix:{os.fsdecode(address)}", "socket denied by manifest")


def _check_exec(exe: Any, args: Any = None) -> None:
    exe = os.fsdecode(exe) if isinstance(exe, (str, bytes, os.PathLike)) else ""
    import shutil
    resolved = exe if os.path.isabs(exe) else (shutil.which(exe) or exe)
    if resolved not in _policy["exec_allow"] and os.path.realpath(resolved) not in _policy["exec_allow"]:
        shown = " ".join(map(str, args))[:200] if isinstance(args, (list, tuple)) else exe
        _violation(f"exec {shown}", "command not in manifest commands")


def _hook(event: str, args: tuple) -> None:
    global _busy
    if _busy:
        return
    _busy = True
    try:
        if event == "open":
            _check_open(*(list(args) + [None, None])[:3])
        elif event == "socket.connect":
            _check_connect(args[1])
        elif event == "subprocess.Popen":
            exe, argv = args[0], args[1]
            _check_exec(exe or (argv[0] if isinstance(argv, (list, tuple)) and argv else argv), argv)
        elif event in ("os.system", "os.posix_spawn", "os.exec"):
            if event == "os.system":
                _check_exec("/bin/sh", ["/bin/sh", "-c", os.fsdecode(args[0])])
            else:
                _check_exec(args[0], args[1] if len(args) > 1 else None)
        elif event in ("os.listdir", "os.scandir"):
            p = os.path.realpath(os.fsdecode(args[0] if args[0] is not None else "."))
            if not isinstance(args[0], int) and not _readable(p):
                _violation(f"list {p}", "read outside manifest read globs")
    finally:
        _busy = False


class _Proxy:
    def __init__(self, target: str, workdir: str | None = None):
        self._target = target
        if workdir:
            self.workdir = workdir

    def __getattr__(self, method: str):
        if method.startswith("_"):
            raise AttributeError(method)

        def call(*args, **kwargs):
            schema_cls = None
            if self._target == "student" and method == "ask":
                if "schema" in kwargs:
                    schema_cls = kwargs["schema"]
                    kwargs["schema"] = schema_cls.model_json_schema()
                elif len(args) >= 3:
                    schema_cls = args[2]
                    args = (*args[:2], schema_cls.model_json_schema(), *args[3:])
            _send({"op": "call", "target": self._target, "method": method,
                   "args": list(args), "kwargs": kwargs})
            reply = json.loads(_rpc_in.readline())
            if not reply.get("ok"):
                import builtins
                exc = getattr(builtins, reply.get("type") or "", None)
                if not (isinstance(exc, type) and issubclass(exc, Exception)):
                    exc = RuntimeError
                raise exc(reply.get("error"))
            out = reply.get("result")
            if schema_cls is not None and isinstance(out, dict):
                out = schema_cls.model_validate(out).model_dump()
            return out

        return call


class _AttrState(dict):
    """Fallback State when harness.state isn't importable: dict with attribute access."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v


def _load_state(data: dict):
    try:
        from harness.state import State  # type: ignore
        return State.model_validate(data)
    except ImportError:
        return _AttrState(data)


def _dump_state(state) -> dict:
    if hasattr(state, "model_dump"):
        return state.model_dump(mode="json")
    return dict(state)


def main() -> None:
    global _rpc_out, _rpc_in, _policy, _enforce
    _rpc_in = sys.stdin
    _rpc_out = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)  # anything the untrusted code prints goes to stderr
    sys.stdout = sys.stderr
    job = json.loads(_rpc_in.readline())
    _policy, _enforce = job["policy"], bool(job.get("enforce"))
    sys.stdin = open(os.devnull)  # routine code must not read the RPC channel
    sys.addaudithook(_hook)
    try:
        if job["kind"] == "routine":
            import importlib.util
            spec = importlib.util.spec_from_file_location("routine", job["routine"])
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            state = _load_state(job["state"])
            tools = _Proxy("tools", _policy["workdir"])
            student = _Proxy("student")
            new = mod.run(state, tools, student)
            _send({"op": "done", "state": _dump_state(new if new is not None else state)})
        else:
            script = job["script"]
            if script.endswith(".py"):
                import runpy
                sys.argv = [script, *job.get("args", [])]
                code = 0
                try:
                    runpy.run_path(script, run_name="__main__")
                except SystemExit as e:
                    code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            else:
                import subprocess
                code = subprocess.run(["/bin/sh", script, *job.get("args", [])]).returncode
            _send({"op": "exit", "code": code})
    except BaseException:
        _send({"op": "error", "error": traceback.format_exc()})


if __name__ == "__main__":
    main()
