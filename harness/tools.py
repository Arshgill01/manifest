"""Tool layer: the five tools, a path jail to the task dir, and manifest enforcement (CONTRACT 2.3).

Every call logs `tool.call`; every refused call also logs `warden.block` and raises `WardenBlock`.
This is defense in depth: the real sandbox is Warden's executor (SPEC 6.3).

Return types (routines rely on these):
  list_files()                    -> list[str]            task-relative posix paths
  read_file(path, start, end)     -> str                  raw text, lines start..end inclusive (1-indexed)
  run_tests(selector=None)        -> {passed, failed, errors, ok, exitCode, output, failures:[{test, error, frames:[{file,line,function}]}]}
  edit_file(path, search, replace)-> {ok, path, error, replacements}
  bash(cmd)                       -> {ok, exitCode, output}
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from harness.log import ROOT, EventLog

FAKE_HOME = ROOT / "demo" / "fakehome"
PYTEST_CMD = "python -m pytest"
PYTEST_ARGS = ["-q", "-p", "no:cacheprovider", "--tb=short", "-rfE", "--color=no"]
OUTPUT_CAP = 20_000
TOOL_TIMEOUT = 60

# commands the tool layer never runs, manifest or not (network / installs / privilege)
DENIED_COMMANDS = {
    "curl", "wget", "nc", "ncat", "netcat", "ssh", "scp", "sftp", "rsync", "ftp", "telnet",
    "pip", "pip3", "uv", "brew", "npm", "npx", "sudo", "su", "open", "osascript", "security",
}
SHELL_META = re.compile(r"[;&|<>`\n]|\$\(")
EMPTY_SELECTORS = {"-", "*", "all", "ALL", "None", "null"}  # small models' ways of saying "everything"
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", ".venv", "node_modules"}


class WardenBlock(PermissionError):
    """A tool call refused by the path jail or the routine's permission manifest."""


class ToolError(Exception):
    """A tool call that ran but could not do what was asked (missing file, bad range, ...)."""


def glob_to_regex(glob: str) -> re.Pattern:
    """Task-relative glob → regex. `**` spans directories, `*`/`?` stay within one segment."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?"); i += 3
        elif glob.startswith("**", i):
            out.append(".*"); i += 2
        elif glob[i] == "*":
            out.append("[^/]*"); i += 1
        elif glob[i] == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(glob[i])); i += 1
    return re.compile("".join(out) + r"\Z")


def matches_any(rel: str, globs: list[str]) -> bool:
    return any(glob_to_regex(g.removeprefix("./")).match(rel) for g in globs)


def _truncate(text: str, cap: int = OUTPUT_CAP) -> str:
    if len(text) <= cap:
        return text
    head = cap * 2 // 3
    return text[:head] + f"\n... [{len(text) - cap} chars truncated] ...\n" + text[-(cap - head):]


class Tools:
    def __init__(self, workdir: Path | str, manifest: dict | None = None, log: EventLog | None = None,
                 *, skill: str = "harness", deadline: float | None = None):
        self.workdir = Path(workdir).resolve()
        self.manifest = manifest
        self.log = log
        self.skill = skill
        self.deadline = deadline  # time.monotonic() value; clamps subprocess timeouts

    # ---- enforcement -------------------------------------------------------------------------

    def _block(self, attempted: str, reason: str) -> None:
        if self.log:
            self.log.emit("warden.block", skill=self.skill, attempted=attempted, reason=reason)
        raise WardenBlock(reason)

    def _resolve(self, path: str, attempted: str) -> tuple[Path, str]:
        if not isinstance(path, str) or not path.strip():
            raise ToolError("path must be a non-empty string")
        p = Path(os.path.expanduser(path.strip())) if path.strip().startswith("~") else Path(path.strip())
        real = (p if p.is_absolute() else self.workdir / p).resolve()
        if real != self.workdir and self.workdir not in real.parents:
            self._block(attempted, f"path {path!r} is outside the task dir (use task-relative paths)")
        return real, (real.relative_to(self.workdir).as_posix() if real != self.workdir else ".")

    def _check(self, kind: str, rel: str, attempted: str) -> None:
        if self.manifest is None:
            return
        globs = self.manifest.get(kind) or []
        if not matches_any(rel, globs):
            self._block(attempted, f"manifest does not allow {kind} of {rel!r} (allowed: {globs})")

    def _check_command(self, cmd: str, attempted: str) -> None:
        try:
            tokens = shlex.split(cmd)
        except ValueError as e:
            self._block(attempted, f"unparseable command: {e}")
        if not tokens:
            raise ToolError("empty command")
        if Path(tokens[0]).name in DENIED_COMMANDS:
            self._block(attempted, f"command {tokens[0]!r} is not allowed (network/install/privilege)")
        if "$" in cmd:
            self._block(attempted, "shell variable expansion is not allowed")
        for tok in tokens:
            for piece in [tok, *tok.split("=", 1)[1:]]:
                if piece.startswith("~") or ".." in Path(piece).parts:
                    self._block(attempted, f"path {piece!r} escapes the task dir")
                if piece.startswith("/"):
                    real = Path(piece).resolve()
                    if real != self.workdir and self.workdir not in real.parents and piece != "/dev/null":
                        self._block(attempted, f"absolute path {piece!r} is outside the task dir")
        if self.manifest is not None:
            if SHELL_META.search(cmd):
                self._block(attempted, "shell operators (; & | < > ` $()) are not allowed under a manifest")
            norm = " ".join(tokens)
            allowed = self.manifest.get("commands") or []
            if not any(norm == p or norm.startswith(p + " ") for p in allowed):
                self._block(attempted, f"command not in manifest (allowed prefixes: {allowed})")

    # ---- plumbing ----------------------------------------------------------------------------

    def _logged(self, tool: str, args: dict, fn: Callable[[], Any], summarize: Callable[[Any], tuple[bool, str]]):
        try:
            result = fn()
        except WardenBlock as e:
            self._emit(tool, args, False, f"blocked: {e}")
            raise
        except Exception as e:
            self._emit(tool, args, False, f"error: {e}")
            raise
        ok, summary = summarize(result)
        self._emit(tool, args, ok, summary)
        return result

    def _emit(self, tool: str, args: dict, ok: bool, summary: str) -> None:
        if self.log:
            short = {k: (v[:300] + "…" if isinstance(v, str) and len(v) > 300 else v) for k, v in args.items()}
            self.log.emit("tool.call", tool=tool, args=short, ok=ok, summary=summary[:300], skill=self.skill)

    def _timeout(self) -> float:
        if self.deadline is None:
            return TOOL_TIMEOUT
        return max(1.0, min(TOOL_TIMEOUT, self.deadline - time.monotonic()))

    def _env(self) -> dict[str, str]:
        bindir = str(Path(sys.executable).parent)
        return {
            "PATH": f"{bindir}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(FAKE_HOME),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "COLUMNS": "200",
        }

    def _sub(self, argv: list[str] | str, shell: bool = False) -> tuple[int, str]:
        """Run a tool subprocess. It executes code the student may have written, so it runs inside Warden's
        kernel sandbox when one is available (Linux bwrap: no network, no $HOME, tests/ read-only)."""
        from warden.sandbox import tool_argv

        argv = tool_argv(argv if not shell else str(argv), self.workdir)
        try:
            p = subprocess.run(argv, cwd=self.workdir, env=self._env(), text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=self._timeout())
            return p.returncode, p.stdout
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            return 124, out + "\n[timed out]"

    # ---- tools -------------------------------------------------------------------------------

    def list_files(self) -> list[str]:
        def go() -> list[str]:
            out = []
            for dirpath, dirnames, filenames in os.walk(self.workdir):
                dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
                for f in sorted(filenames):
                    if f.endswith(".pyc") or f == ".DS_Store":
                        continue
                    rel = (Path(dirpath) / f).relative_to(self.workdir).as_posix()
                    if self.manifest is None or matches_any(rel, self.manifest.get("read") or []):
                        out.append(rel)
            return sorted(out)
        return self._logged("list_files", {}, go, lambda r: (True, f"{len(r)} files"))

    def read_file(self, path: str, start: int | None = None, end: int | None = None) -> str:
        args = {"path": path, "start": start, "end": end}

        def go() -> str:
            real, rel = self._resolve(path, f"read {path}")
            self._check("read", rel, f"read {rel}")
            if not real.is_file():
                raise ToolError(f"no such file: {rel}")
            lines = real.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            s = max(1, int(start)) if start else 1
            e = min(len(lines), int(end)) if end else len(lines)
            if lines and s > len(lines):
                raise ToolError(f"start line {s} is past the end of {rel} ({len(lines)} lines)")
            return "".join(lines[s - 1:e])
        return self._logged("read_file", args, go, lambda r: (True, f"read {path} ({r.count(chr(10))} lines)"))

    def run_tests(self, selector: str | None = None) -> dict:
        args = {"selector": selector}

        def go() -> dict:
            sel = selector.strip() if isinstance(selector, str) else None
            extra = self._selector_args(sel) if sel and sel not in EMPTY_SELECTORS else []
            if self.manifest is not None:
                self._check_command(" ".join([PYTEST_CMD, *extra]), f"run_tests {selector or ''}".strip())
            code, out = self._sub([sys.executable, "-m", "pytest", *PYTEST_ARGS, *extra])
            out = out.replace(f"{self.workdir}/", "")
            return {**parse_pytest(out, self.workdir), "exitCode": code, "output": _truncate(out)}
        return self._logged("run_tests", args, go,
                            lambda r: (True, f"{r['failed']} failed, {r['passed']} passed" + (f" ({selector})" if selector and selector.strip() not in EMPTY_SELECTORS else "")))

    def _selector_args(self, selector: str) -> list[str]:
        try:
            tokens = shlex.split(selector)
        except ValueError as e:
            raise ToolError(f"bad selector: {e}")
        out, i = [], 0
        while i < len(tokens):
            t = tokens[i]
            if t in ("-k", "-x") or t.startswith("-k"):
                out.append(t)
                if t == "-k" and i + 1 < len(tokens):
                    out.append(tokens[i + 1]); i += 1
            elif t.startswith("-"):
                raise ToolError(f"selector option {t!r} not allowed (use test paths, node ids, -k, -x)")
            else:
                self._resolve(t.split("::", 1)[0], f"run_tests {selector}")
                out.append(t)
            i += 1
        return out

    def edit_file(self, path: str, search: str, replace: str) -> dict:
        args = {"path": path, "search": search, "replace": replace}

        def go() -> dict:
            real, rel = self._resolve(path, f"edit {path}")
            self._check("write", rel, f"write {rel}")
            if not isinstance(search, str) or not isinstance(replace, str):
                raise ToolError("search and replace must be strings")
            if not real.exists():
                if search == "":
                    real.parent.mkdir(parents=True, exist_ok=True)
                    real.write_text(replace, encoding="utf-8")
                    return {"ok": True, "path": rel, "error": None, "replacements": 1}
                return {"ok": False, "path": rel, "error": f"no such file: {rel}", "replacements": 0}
            text = real.read_text(encoding="utf-8")
            n = text.count(search) if search else 0
            if n != 1:
                why = ("search text is empty" if not search else
                       "search text not found (it must match the file exactly, including indentation)" if n == 0 else
                       f"search text matches {n} places; include more surrounding lines so it is unique")
                return {"ok": False, "path": rel, "error": why, "replacements": 0}
            real.write_text(text.replace(search, replace, 1), encoding="utf-8")
            return {"ok": True, "path": rel, "error": None, "replacements": 1}
        return self._logged("edit_file", args, go,
                            lambda r: (r["ok"], f"edited {r['path']}" if r["ok"] else f"{r['path']}: {r['error']}"))

    def bash(self, cmd: str) -> dict:
        args = {"cmd": cmd}

        def go() -> dict:
            if not isinstance(cmd, str):
                raise ToolError("cmd must be a string")
            self._check_command(cmd, cmd)
            code, out = self._sub(cmd, shell=True)
            return {"ok": code == 0, "exitCode": code, "output": _truncate(out, 8000)}
        return self._logged("bash", args, go, lambda r: (r["ok"], f"exit {r['exitCode']}"))


# ---- pytest output parsing -------------------------------------------------------------------

_SECTION = re.compile(r"^=+ (.+?) =+$")
_BLOCK = re.compile(r"^_{3,} (.+?) _{3,}$")
_FRAME = re.compile(r"^(?P<file>[^\s:][^:]*?):(?P<line>\d+): in (?P<func>.+)$")
_SYNTAX = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+)')
_SUMMARY = re.compile(r"^(FAILED|ERROR) (\S+)(?: - (.*))?$")
_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")
_DURATION = re.compile(r"\bin [\d.]+s\b")


def _relpath(file: str, workdir: Path) -> str:
    p = Path(file)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(workdir).as_posix()
        except ValueError:
            return file
    return p.as_posix()


def _in_repo(file: str, workdir: Path) -> bool:
    """Frames inside the task dir only; pytest/importlib/stdlib frames are noise for diagnosis."""
    if file.startswith("<"):
        return False
    p = Path(file)
    if not p.is_absolute():
        return ".venv" not in p.parts and "site-packages" not in p.parts
    return not _relpath(file, workdir).startswith("/")


def parse_pytest(output: str, workdir: Path) -> dict:
    """Parse `pytest -q --tb=short -rfE` output into counts + failures with traceback frames."""
    lines = output.splitlines()
    counts = {"passed": 0, "failed": 0, "errors": 0}
    for line in reversed(lines):
        found = _COUNT.findall(line)
        if found and _DURATION.search(line):
            for n, kind in found:
                key = "errors" if kind.startswith("error") else kind
                if key in counts:
                    counts[key] = int(n)
            break

    blocks: list[tuple[str, list[str]]] = []
    section, current = None, None
    for line in lines:
        m = _SECTION.match(line)
        if m:
            section = m.group(1).strip().upper()
            current = None
            continue
        if section not in ("FAILURES", "ERRORS"):
            continue
        b = _BLOCK.match(line)
        if b:
            current = (b.group(1).strip(), [])
            blocks.append(current)
        elif current is not None:
            current[1].append(line)

    summary = [(m.group(1), m.group(2), m.group(3) or "") for m in map(_SUMMARY.match, lines) if m]
    used: set[int] = set()

    def nodeid_for(header: str) -> str:
        name = re.sub(r"^ERROR (at (setup|teardown) of|collecting) ", "", header)
        for i, (_, nid, _) in enumerate(summary):
            short = nid.split("::", 1)[1].replace("::", ".") if "::" in nid else nid
            if i not in used and (short == name or nid == name):
                used.add(i)
                return nid
        return name

    failures = []
    for header, body in blocks:
        frames = []
        for line in body:
            fm = _FRAME.match(line)
            if fm and _in_repo(fm["file"], workdir):
                frames.append({"file": _relpath(fm["file"], workdir), "line": int(fm["line"]), "function": fm["func"].strip()})
        err_lines = [l[1:].strip() for l in body if l.startswith("E ")]
        for line in err_lines:
            sm = _SYNTAX.search(line)
            if sm and _in_repo(sm["file"], workdir):
                frames.append({"file": _relpath(sm["file"], workdir), "line": int(sm["line"]), "function": "<syntax>"})
        error = "\n".join(err_lines)[:600] or (body[-1].strip() if body else "")
        failures.append({"test": nodeid_for(header), "error": error, "frames": frames})

    for i, (_, nid, msg) in enumerate(summary):  # failures pytest summarised but printed no block for
        if i not in used and not any(f["test"] == nid for f in failures):
            failures.append({"test": nid, "error": msg, "frames": []})

    failed = counts["failed"] + counts["errors"]
    if failed == 0 and failures:
        failed = len(failures)
    return {"passed": counts["passed"], "failed": failed, "errors": counts["errors"],
            "ok": failed == 0 and counts["passed"] > 0, "failures": failures}
