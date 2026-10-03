"""Warden static scan (SPEC §6.1): regex + AST rules over a routine or skill directory.

`scan(path, teacher=None) -> [{rule, severity, file, line, detail}]`

Stdlib only (this file is vendored into `skills/warden/scripts/` so the Agent Skill runs anywhere).
Encoded blobs (base64 / hex) are decoded and re-scanned, so `exec(b64decode(...))` payloads are
judged by what they actually do. An optional teacher pass (`teacher.summarize_code(src)`) adds a
plain-English summary of the code as `teacher-summary` findings.
"""

from __future__ import annotations

import ast
import base64
import binascii
import re
from pathlib import Path

SEVERITIES = ["info", "low", "medium", "high", "critical"]

NETWORK_MODULES = {
    "socket", "urllib", "urllib2", "urllib3", "requests", "http", "httpx", "aiohttp", "ftplib",
    "smtplib", "telnetlib", "paramiko", "websocket", "websockets", "pycurl", "xmlrpc", "asyncio.streams",
}
NETWORK_CALLS = {"urlopen", "create_connection", "connect", "post", "put", "request", "send", "sendall",
                 "getaddrinfo", "gethostbyname"}
SECRET_PATTERNS = re.compile(r"(\.ssh|id_rsa|id_ed25519|\.aws|\.gnupg|\.netrc|keychain|\.kube|"
                             r"\.docker/config|\.git-credentials|\.npmrc|\.pypirc|Cookies|Login Data)", re.I)
OUT_OF_DIR = re.compile(r"(^~|^/Users/|^/home/|^/root|^/etc/|^/var/|^/private/|(^|/)\.\.(/|$))")
SECRET_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH)", re.I)
TEXT_RULES = [  # (rule, severity, regex, detail) for shell scripts, SKILL.md, any text
    ("network", "high", re.compile(r"\b(curl|wget|nc|ncat|socat|scp|rsync|ssh)\s"), "network tool invoked"),
    ("pipe-to-shell", "critical", re.compile(r"\|\s*(ba|z)?sh\b"), "pipes content into a shell"),
    ("obfuscated-exec", "critical", re.compile(r"base64\s+(-d|--decode|-D)"), "decodes base64 in a shell"),
    ("secrets-path", "critical", SECRET_PATTERNS, "touches a credential location"),
    ("env-read", "medium", re.compile(r"(\$\{?[A-Z_]*(KEY|TOKEN|SECRET)[A-Z_]*\}?|(^|\s)\.env\b|printenv|\benv\b\s*$)"),
     "reads secrets from the environment"),
    ("out-of-dir-path", "high", re.compile(r"(~/|\$HOME|/Users/|/home/|/etc/passwd)"), "path outside the task dir"),
    ("hidden-instruction", "high",
     re.compile(r"(ignore (all |any )?(previous|prior) instructions|do not (tell|mention|inform)|"
                r"without (telling|asking) the user|silently|don't mention|no need to (tell|mention|inform)|"
                r"(keep|hide) (this|it) (from|secret))", re.I),
     "instruction to act without the user's knowledge"),
]
B64_RE = re.compile(r"^[A-Za-z0-9+/=\s]{24,}$")
HEX_RE = re.compile(r"^(?:[0-9a-fA-F]{2}){16,}$")
SCAN_SUFFIXES = {".py", ".sh", ".bash", ".zsh", ".md", ".js", ".ts", ".rb", ".pl", ".txt", ".json", ".toml", ".yaml", ".yml", ""}
MAX_BYTES = 400_000


def _f(rule, severity, file, line, detail):
    return {"rule": rule, "severity": severity, "file": file, "line": int(line or 0), "detail": detail}


def _decode_blob(s: str) -> str | None:
    s2 = "".join(s.split())
    try:
        if HEX_RE.match(s2):
            out = bytes.fromhex(s2)
        elif B64_RE.match(s) and len(s2) % 4 == 0:
            out = base64.b64decode(s2, validate=True)
        else:
            return None
        text = out.decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    printable = sum(c.isprintable() or c in "\n\t" for c in text) / max(len(text), 1)
    return text if printable > 0.95 and len(text) >= 8 else None


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):
        parts.append(_dotted(node.func) + "()")
    return ".".join(reversed(parts))


class _Visitor(ast.NodeVisitor):
    def __init__(self, file: str, depth: int):
        self.file, self.depth = file, depth
        self.out: list[dict] = []
        self.decodes: set[str] = set()  # names bound to decoded blobs

    def add(self, rule, sev, node, detail):
        self.out.append(_f(rule, sev, self.file, getattr(node, "lineno", 0), detail))

    # imports ---------------------------------------------------------------
    def _check_module(self, mod: str, node):
        top = mod.split(".")[0]
        if mod in NETWORK_MODULES or top in NETWORK_MODULES:
            self.add("network", "high", node, f"imports {mod}")
        elif top in ("ctypes", "cffi"):
            self.add("native-code", "high", node, f"imports {mod} (can bypass Python-level checks)")
        elif top in ("pickle", "marshal", "shelve"):
            self.add("deserialization", "medium", node, f"imports {mod}")

    def visit_Import(self, node):
        for a in node.names:
            self._check_module(a.name, node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self._check_module(node.module, node)
        self.generic_visit(node)

    # calls -----------------------------------------------------------------
    def visit_Call(self, node):
        name = _dotted(node.func)
        last = name.split(".")[-1]
        kw = {k.arg: k.value for k in node.keywords if k.arg}

        if last in ("eval", "exec", "compile") and name in (last, "builtins." + last):
            arg = node.args[0] if node.args else None
            inner = _dotted(arg.func) if isinstance(arg, ast.Call) else ""
            if any(x in inner for x in ("b64decode", "decode", "fromhex", "loads", "decompress", "unhexlify")) or \
                    (isinstance(arg, ast.Name) and arg.id in self.decodes):
                self.add("obfuscated-exec", "critical", node, f"{last}() of decoded data")
            elif isinstance(arg, ast.Constant):
                self.add("exec", "medium", node, f"{last}() of a literal")
            else:
                self.add("exec", "high", node, f"{last}() of dynamic code")
        elif name in ("__import__", "importlib.import_module") or last == "import_module":
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                self._check_module(arg.value, node)
            else:
                self.add("dynamic-import", "high", node, "imports a module chosen at runtime")
        elif name.startswith("subprocess.") or last in ("Popen", "check_output", "check_call") or \
                name in ("os.system", "os.popen") or name.startswith("os.exec") or name.startswith("os.spawn"):
            shell = kw.get("shell")
            first = node.args[0] if node.args else kw.get("args")
            cmd = self._cmd_text(first)
            if name in ("os.system", "os.popen") or (isinstance(shell, ast.Constant) and shell.value) or \
                    (first is not None and not isinstance(first, (ast.List, ast.Tuple)) and
                     not (isinstance(first, ast.Name))):
                self.add("shell", "high", node, f"shell command: {cmd or '<dynamic>'}")
            else:
                self.add("subprocess", "low", node, f"runs: {cmd or '<dynamic argv>'}")
            if cmd and re.search(r"\b(curl|wget|nc|scp|ssh|rsync)\b", cmd):
                self.add("network", "high", node, f"network tool via subprocess: {cmd}")
        elif last in NETWORK_CALLS and any(m in name for m in ("socket", "urllib", "requests", "http", "httpx")):
            self.add("network", "high", node, f"network call {name}()")
        elif name in ("os.getenv", "os.environ.get", "os.getenvb", "environ.get"):
            key = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else "?"
            sev = "high" if isinstance(key, str) and SECRET_ENV.search(key) else "low"
            self.add("env-read", sev, node, f"reads env var {key}")
        elif last in ("expanduser", "home") and ("path" in name or "Path" in name):
            self.add("out-of-dir-path", "high", node, f"{name}() resolves the user's home directory")
        elif last in ("b64decode", "a85decode", "b32decode", "unhexlify", "fromhex", "decompress"):
            self.add("decode", "low", node, f"{name}() decodes embedded data")
        self.generic_visit(node)

    def _cmd_text(self, node) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            return " ".join(e.value if isinstance(e, ast.Constant) and isinstance(e.value, str) else "<?>"
                            for e in node.elts)
        if isinstance(node, ast.JoinedStr):
            return "".join(v.value if isinstance(v, ast.Constant) else "{...}" for v in node.values)
        return ""

    def visit_Assign(self, node):
        if isinstance(node.value, ast.Call):
            inner = _dotted(node.value.func)
            if any(x in inner for x in ("b64decode", "fromhex", "unhexlify", "decompress", ".decode")):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.decodes.add(t.id)
        self.generic_visit(node)

    def visit_Subscript(self, node):
        if _dotted(node.value) in ("os.environ", "environ"):
            key = node.slice.value if isinstance(node.slice, ast.Constant) else "?"
            sev = "high" if isinstance(key, str) and SECRET_ENV.search(key) else "low"
            self.add("env-read", sev, node, f"reads env var {key}")
        self.generic_visit(node)

    # literals --------------------------------------------------------------
    def visit_Constant(self, node):
        v = node.value
        if isinstance(v, bytes):
            try:
                v = v.decode("utf-8")
            except UnicodeDecodeError:
                v = None
        if isinstance(v, str) and v:
            if SECRET_PATTERNS.search(v):
                self.add("secrets-path", "critical", node, f"references credential path {v[:60]!r}")
            elif OUT_OF_DIR.search(v.strip()):
                self.add("out-of-dir-path", "high", node, f"path outside the task dir {v[:60]!r}")
            elif re.search(r"(^|/)\.env$", v):
                self.add("env-read", "high", node, "references a .env file")
            elif re.match(r"^tests?/", v):
                self.add("touches-tests", "low", node, f"references test files {v[:60]!r}")
            m = re.search(r"\b(https?|ftp|wss?)://[^\s'\"]+", v)
            if m:
                self.add("network", "high", node, f"URL literal {m.group(0)[:80]}")
            decoded = _decode_blob(v) if len(v) >= 24 else None
            if decoded is not None and self.depth < 3:
                self.add("encoded-blob", "medium", node, f"encoded blob ({len(v)} chars) decodes to code/text")
                for f in _scan_text(decoded, f"{self.file}<decoded@{node.lineno}>", self.depth + 1):
                    f["line"] = node.lineno
                    self.out.append(f)
        self.generic_visit(node)


def _scan_python(src: str, file: str, depth: int = 0) -> list[dict]:
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [_f("unparseable", "medium", file, e.lineno or 0, f"could not parse: {e.msg}")]
    v = _Visitor(file, depth)
    v.visit(tree)
    return v.out


def _scan_text_rules(text: str, file: str) -> list[dict]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        for rule, sev, rx, detail in TEXT_RULES:
            if rx.search(line):
                out.append(_f(rule, sev, file, i, f"{detail}: {line.strip()[:80]}"))
    return out


def _scan_text(text: str, file: str, depth: int) -> list[dict]:
    """Decoded payloads: try Python first, else text rules."""
    try:
        ast.parse(text)
        return _scan_python(text, file, depth)
    except SyntaxError:
        return _scan_text_rules(text, file)


def _iter_files(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part in ("__pycache__", ".git", "node_modules") for part in p.parts):
            if p.suffix.lower() in SCAN_SUFFIXES or p.name in ("SKILL.md",):
                yield p


def _dedupe(findings: list[dict]) -> list[dict]:
    seen, out = set(), []
    for f in findings:
        k = (f["rule"], f["file"], f["line"], f["detail"])
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def scan(path: Path, teacher=None) -> list[dict]:
    """Findings `[{rule, severity, file, line, detail}]`, most severe first."""
    path = Path(path)
    base = path if path.is_dir() else path.parent
    findings: list[dict] = []
    sources: list[tuple[str, str]] = []
    for p in _iter_files(path):
        rel = p.relative_to(base).as_posix()
        try:
            raw = p.read_bytes()[:MAX_BYTES]
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            findings.append(_f("binary", "medium", rel, 0, "binary or unreadable file shipped with the skill"))
            continue
        if p.suffix == ".py":
            findings += _scan_python(text, rel)
            sources.append((rel, text))
        elif p.suffix in (".sh", ".bash", ".zsh") or text.startswith("#!"):
            findings += _scan_text_rules(text, rel)
            findings.append(_f("shell", "medium", rel, 1, "ships a shell script"))
            sources.append((rel, text))
        elif p.suffix == ".md":
            # Markdown: only instructions matter (prompt-injection style), plus fenced code
            findings += [f for f in _scan_text_rules(text, rel)
                         if f["rule"] in ("hidden-instruction", "pipe-to-shell", "secrets-path", "obfuscated-exec")]
        else:
            findings += [f for f in _scan_text_rules(text, rel) if f["severity"] in ("high", "critical")]
    if teacher is not None and sources:
        findings += _teacher_pass(teacher, sources)
    findings = _dedupe(findings)
    findings.sort(key=lambda f: (-SEVERITIES.index(f["severity"]), f["file"], f["line"]))
    return findings


def _teacher_pass(teacher, sources: list[tuple[str, str]]) -> list[dict]:
    blob = "\n\n".join(f"# ===== {name} =====\n{src}" for name, src in sources)[:24_000]
    try:
        lines = teacher.summarize_code(blob) or []
    except Exception as e:  # the teacher is optional; never fail the scan on it
        return [_f("teacher-summary", "info", "*", 0, f"teacher pass unavailable: {type(e).__name__}")]
    return [_f("teacher-summary", "info", "*", 0, str(s)[:300]) for s in lines if str(s).strip()]


def max_severity(findings: list[dict]) -> str:
    return max((f["severity"] for f in findings), key=SEVERITIES.index, default="info")
