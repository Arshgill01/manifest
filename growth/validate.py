"""Candidate validation for v2 growth (SPEC §5.4, paper §3.4): before anything runs.

    check_changeset(changes, current, scope=..., budget=L, banned=...) -> Verdict

- every changed routine is a valid module (≤150 lines, NAME, applies(state), run(state, tools, student));
- seeds are immutable; existing routines are never removed (from the registry or the `order`);
- **no deletions**: every top-level function of an existing routine must still be defined;
- **trace scope**: the body of an existing routine may change only if it ran in some window trace;
  trigger-only changes (`applies`, module constants) are always allowed (registry order + applies() are
  the dispatcher, the paper's `main`);
- **edit budget**: d_fun = added + modified top-level functions (+1 for other changed module code)
  summed over all changes, must be ≤ L;
- **specificity lint**: no task ids, domain names or distinctive template module names anywhere in the
  source (identifiers, strings or comments), so routines can't special-case the practice tasks.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from harness.teacher import SEED_NAMES, check_routine_source

ROOT = Path(__file__).resolve().parent.parent
TRIGGER_ONLY = {"applies"}
# template module names that are ordinary words in a generic debugging routine; not banned
GENERIC_MODULES = {"__init__", "window", "report", "schema", "validate", "reader", "pipeline", "headers", "clock",
                   "resources", "transforms", "aggregate"}


class ValidationError(ValueError):
    """A candidate broke a growth constraint; the message is shown to the teacher on its one retry."""


@dataclass
class Verdict:
    ok: bool
    reason: str = ""
    d_fun: int = 0
    per_routine: dict[str, dict] = field(default_factory=dict)  # name -> {added, modified, removed, other, edit}


def _units(src: str) -> tuple[dict[str, str], str]:
    """Top-level functions/classes -> normalised AST dump; plus a dump of all other top-level code."""
    tree = ast.parse(src)
    funcs: dict[str, str] = {}
    other = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            funcs[node.name] = ast.dump(node, include_attributes=False)
        elif isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
                and isinstance(node.value.value, str):
            continue  # docstrings / bare strings don't count
        else:
            other.append(ast.dump(node, include_attributes=False))
    return funcs, "\n".join(other)


def fn_diff(old: str | None, new: str) -> dict:
    nf, no = _units(new)
    if old is None:
        return {"added": sorted(nf), "modified": [], "removed": [], "other": bool(no.strip()), "edit": False}
    of, oo = _units(old)
    return {
        "added": sorted(set(nf) - set(of)),
        "modified": sorted(k for k in set(nf) & set(of) if nf[k] != of[k]),
        "removed": sorted(set(of) - set(nf)),
        "other": no != oo,
        "edit": True,
    }


def d_fun(diff: dict) -> int:
    if not diff["edit"]:
        return len(diff["added"])  # a new routine costs its functions (module constants are free)
    return len(diff["added"]) + len(diff["modified"]) + (1 if diff["other"] else 0)


def banned_terms(task_ids: list[str] | None = None) -> list[str]:
    """Task ids, domain names, distinctive template module names (from tasks/templates + tasks/index.json)."""
    terms: set[str] = set()
    templates = ROOT / "tasks" / "templates"
    splits = ROOT / "tasks" / "splits.json"
    novel = set(json.loads(splits.read_text()).get("novelDomains", [])) if splits.exists() else set()
    if templates.is_dir():
        for d in templates.iterdir():
            if d.is_dir():
                terms.add(d.name)
                if d.name in novel:
                    continue  # held-out-only domains: the teacher can't know their module names; ban only the name
                for mod in (d / "src").glob("*/*.py"):
                    if mod.stem not in GENERIC_MODULES:
                        terms.add(mod.stem)
    index = ROOT / "tasks" / "index.json"
    if index.exists():
        terms |= set(json.loads(index.read_text()))
    terms |= set(task_ids or [])
    return sorted(t for t in terms if len(t) >= 4)


def lint_specificity(src: str, terms: list[str]) -> list[str]:
    hits = []
    low = src.lower()
    for t in terms:
        if re.search(rf"(?<![a-z0-9]){re.escape(t.lower())}(?![a-z0-9])", low):
            hits.append(t)
    return hits


def check_changeset(changes: list[dict], current: dict[str, str], *, scope: set[str], budget: int,
                    banned: list[str], order: list[str] | None = None, restrict_scope: bool = True) -> Verdict:
    """`current`: grown routine name -> source (seeds excluded). `scope`: routines that ran in window traces."""
    if not changes:
        return Verdict(False, "no changes proposed")
    seen: set[str] = set()
    per: dict[str, dict] = {}
    total = 0
    for ch in changes:
        name = ch.get("name", "")
        if name in seen:
            return Verdict(False, f"routine {name!r} appears twice in changes")
        seen.add(name)
        if name in SEED_NAMES:
            return Verdict(False, f"seed routine {name!r} is immutable; add a new routine instead")
        try:
            check_routine_source(ch.get("routine_py", ""), name)
        except ValueError as e:
            return Verdict(False, f"{name}: {e}")
        diff = fn_diff(current.get(name), ch["routine_py"])
        per[name] = diff
        if diff["removed"]:
            return Verdict(False, f"{name}: existing functions may not be deleted ({', '.join(diff['removed'])})")
        if diff["edit"] and restrict_scope and name not in scope:
            body = (set(diff["added"]) | set(diff["modified"])) - TRIGGER_ONLY
            if body:
                return Verdict(False, f"{name} did not run in any window trace, so only its trigger (applies) and "
                                      f"constants may change; you changed {', '.join(sorted(body))}")
        hits = lint_specificity(ch["routine_py"] + "\n" + ch.get("trigger_description", ""), banned)
        if hits:
            return Verdict(False, f"{name}: task-specific terms are not allowed in routines ({', '.join(hits[:6])}); "
                                  f"routines must work on any Python repository")
        total += d_fun(diff)
    if total > budget:
        return Verdict(False, f"edit budget exceeded: {total} functions added/modified (limit {budget})", total, per)
    if order is not None:
        expected = set(current) | seen
        if set(order) != expected:
            missing = sorted(expected - set(order))
            extra = sorted(set(order) - expected)
            return Verdict(False, "`order` must list every grown routine exactly once"
                                  + (f"; missing {missing}" if missing else "") + (f"; unknown {extra}" if extra else ""),
                           total, per)
    return Verdict(True, "", total, per)
