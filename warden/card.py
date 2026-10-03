"""Bordered terminal permission card for a Warden manifest. Stdlib only (vendored into the skill)."""

from __future__ import annotations

import os
import re
import sys
import unicodedata

WIDTH = 74  # inner content width
SEV_TAG = {"critical": "CRIT", "high": "HIGH", "medium": "MED ", "low": "LOW ", "info": "INFO"}
VERDICT_STYLE = {
    "ok": {"edge": "32", "badge": ("1", "30", "42"), "label": "OK — within the default grant"},
    "review": {"edge": "33", "badge": ("1", "30", "43"), "label": "REVIEW — wants more than the default"},
    "dangerous": {"edge": "31", "badge": ("1", "97", "41"), "label": "DANGEROUS — do not install"},
}
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def use_color(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def _color(on: bool, text: str, *codes: str) -> str:
    if not on or not codes:
        return text
    return "\x1b[" + ";".join(codes) + "m" + text + "\x1b[0m"


def _vis_width(s: str) -> int:
    s = _ANSI.sub("", s)
    total = 0
    for ch in s:
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in "WF" else 1
    return total


def _truncate(s: str, width: int) -> str:
    if _vis_width(s) <= width:
        return s
    plain = _ANSI.sub("", s)
    return plain[: max(width - 1, 0)] + "…"


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if not cur:
            cur = w
        elif _vis_width(cur) + 1 + _vis_width(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return [_truncate(l, width) for l in lines] or [""]


def render(m: dict, *, color: bool | None = None, max_findings: int = 8,
           footer: list[str] | None = None) -> str:
    on = use_color() if color is None else color
    style = VERDICT_STYLE.get(m.get("verdict", "review"), VERDICT_STYLE["review"])
    edge = style["edge"]
    W = WIDTH

    def bar(left: str, right: str) -> str:
        return _color(on, left + "─" * W + right, edge)

    def row(content: str = "", pad: int = 1) -> str:
        inner = " " * pad + content
        gap = W - pad - _vis_width(content)
        inner += " " * max(gap, 0)
        return _color(on, "│", edge) + inner + _color(on, "│", edge)

    def rule() -> str:
        return _color(on, "├" + "─" * W + "┤", edge)

    def field(label: str, values: list[str], empty: str, value_color: tuple = ()) -> list[str]:
        head = label.ljust(10)
        vals = values or [empty]
        painted = [_color(on, v, *value_color) if value_color and values else
                   (_color(on, v, "2") if not values else v) for v in vals]
        out, line, first = [], "", True
        avail = W - 1 - 11
        for v in painted:
            piece = v if first else ", " + v
            if _vis_width(line) + _vis_width(piece) > avail and line:
                out.append(row(head + line))
                head, line, first = " " * 10, v, True
                continue
            line += piece
            first = False
        out.append(row(head + line))
        return out

    net = m.get("network")
    net_txt = "ALLOWED" if net else "denied"
    net_color = ("1", "31") if net else ("32",)

    lines = [bar("┌", "┐")]
    badge = _color(on, " WARDEN ", "1", "97", "44")
    skill = _color(on, m.get("skill", "?"), "1")
    lines.append(row(badge + "  skill: " + skill))
    lines.append(rule())
    verdict_line = _color(on, " " + style["label"] + " ", *style["badge"])
    lines.append(row(verdict_line))
    src = m.get("declaredFrom")
    if src:
        lines.append(row(_color(on, "permissions declared via: " + src, "2")))
    lines.append(rule())

    lines += field("read", m.get("read", []), "(none)")
    lines += field("write", m.get("write", []), "(none)")
    lines += field("commands", m.get("commands", []), "(none)")
    lines.append(row("network".ljust(10) + _color(on, net_txt, *net_color)))

    undecl = m.get("undeclared") or {}
    extra = list(undecl.get("read", [])) + (["network"] if undecl.get("network") else []) + \
        list(undecl.get("commands", []))
    if extra:
        lines.append(rule())
        lines.append(row(_color(on, "UNDECLARED (did it, never asked):", "1", "31")))
        for ln in field("", extra, "", value_color=("31",)):
            lines.append(ln)

    findings = m.get("findings", [])
    reasons = m.get("reasons", [])
    if reasons:
        lines.append(rule())
        lines.append(row(_color(on, "why:", "1")))
        shown = reasons[:max_findings]
        for r in shown:
            for i, seg in enumerate(_wrap(r, W - 4)):
                lines.append(row(("  • " if i == 0 else "    ") + seg))
        if len(reasons) > len(shown):
            lines.append(row(_color(on, f"  … and {len(reasons) - len(shown)} more", "2")))

    if findings:
        lines.append(rule())
        counts = {}
        for f in findings:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1
        summary = "  ".join(f"{SEV_TAG[s].strip()}:{counts[s]}"
                            for s in ("critical", "high", "medium", "low", "info") if s in counts)
        lines.append(row("findings   " + _color(on, summary, "1")))

    if footer:
        lines.append(rule())
        for fl in footer:
            for seg in _wrap(fl, W - 2):
                lines.append(row(seg))

    lines.append(bar("└", "┘"))
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    data = json.load(sys.stdin)
    print(render(data))
