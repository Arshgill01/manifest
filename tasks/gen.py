"""Deterministic task generator.

    uv run python -m tasks.gen            # build tasks/generated/, splits.json, index.json
    uv run python -m tasks.gen --check    # verify only, print the table, write nothing

Every task = a clean template package + exactly one mutation from `tasks/mutations.py`.
Nothing is trusted: each task is built in a scratch dir and must (1) pass clean, (2) fail
mutated, (3) pass again once the mutation is reverted, (4) satisfy every bug shape it claims.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .mutations import DEMO_MUTATIONS, MUTATIONS, Edit, Mutation

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "templates"
GENERATED = ROOT / "generated"
SEED = 1337
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc")

TASK_MD = """# Task

The test suite is failing. Make it pass without editing tests.

Run the tests with:

    python -m pytest -q

Source code lives in `src/{pkg}/`. Tests live in `tests/` and must not be modified.
"""

CONFTEST = 'import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))\n'
PYTEST_INI = "[pytest]\naddopts = -p no:cacheprovider\n"

# Split sizes. `full` is SPEC §3; `core` is the fast set for an 8 GB laptop
# (~9 tasks keeps a whole growth run inside the time budget).
PROFILES = {
    "full": {"train": 12, "gate": 6, "heldout": 8},
    "core": {"train": 3, "gate": 3, "heldout": 3},
}
NOVEL_DOMAIN = "csvflow"   # appears only in held-out
SHAPES = ("deep-call-chain", "one-root-many", "regression-trap", "misleading-surface")


# ---------------------------------------------------------------- pytest helpers

@dataclass
class TestRun:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    crash_sites: dict[str, str] = field(default_factory=dict)   # test -> "file:line" where it blew up
    output: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed and bool(self.passed)


_RESULT = re.compile(r"^(PASSED|FAILED|ERROR) (tests/\S+::[^\s]+)")
_CRASH = re.compile(r"^(/\S+?\.py):(\d+): ")


def pytest_env() -> dict[str, str]:
    # Edits like max->min keep file size and land in the same second: a cached .pyc would be
    # reused and the edit silently ignored. Never write bytecode in task dirs.
    import os

    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    return env


def run_pytest(task_dir: Path, timeout: int = 60) -> TestRun:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-rA", "-q", "--tb=line", "-p", "no:cacheprovider", "-o", "console_output_style=classic"],
        cwd=task_dir, capture_output=True, text=True, timeout=timeout, env=pytest_env(),
    )
    run = TestRun(output=proc.stdout + proc.stderr)
    crash_lines = []
    for line in proc.stdout.splitlines():
        if m := _RESULT.match(line):
            (run.passed if m.group(1) == "PASSED" else run.failed).append(m.group(2))
        elif m := _CRASH.match(line):
            crash_lines.append(f"{Path(m.group(1)).resolve().relative_to(task_dir.resolve())}:{m.group(2)}"
                               if Path(m.group(1)).resolve().is_relative_to(task_dir.resolve()) else f"{m.group(1)}:{m.group(2)}")
    # --tb=line prints one crash line per failure, in failure order
    for test, site in zip(run.failed, crash_lines):
        run.crash_sites[test] = site
    return run


def apply_edits(task_dir: Path, edits: tuple[Edit, ...]) -> None:
    for e in edits:
        path = task_dir / e.file
        src = path.read_text()
        count = src.count(e.search)
        if count != 1:
            raise ValueError(f"{e.file}: search text found {count} times (need exactly 1): {e.search!r}")
        path.write_text(src.replace(e.search, e.replace))


def mutated_line(task_dir: Path, edit: Edit) -> int:
    """1-based line where the edit's first differing line sits (in the pre-edit file)."""
    src = (task_dir / edit.file).read_text()
    start = src[: src.index(edit.search)].count("\n") + 1
    new = edit.replace.splitlines()
    for i, line in enumerate(edit.search.splitlines()):
        if i >= len(new) or new[i] != line:
            return start + i
    return start


def revert_edits(edits: tuple[Edit, ...]) -> tuple[Edit, ...]:
    return tuple(Edit(e.file, e.replace, e.search) for e in reversed(edits))


def function_span(path: Path, qualname: str) -> tuple[int, int]:
    """1-based [start, end] lines of `func` or `Class.method` in a source file."""
    import ast

    tree = ast.parse(path.read_text())
    parts = qualname.split(".")
    nodes = tree.body
    found = None
    for part in parts:
        found = next((n for n in nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == part), None)
        if found is None:
            raise ValueError(f"{qualname} not found in {path}")
        nodes = found.body
    return found.lineno, found.end_lineno


# ---------------------------------------------------------------- build + verify

@dataclass
class Built:
    mutation: Mutation
    failing: list[str]
    passing: list[str]
    root_line: int
    span: tuple[int, int]
    shapes_ok: dict[str, str]          # shape -> evidence
    errors: list[str]


def copy_template(domain: str, dest: Path) -> None:
    shutil.copytree(TEMPLATES / domain, dest, ignore=IGNORE)
    (dest / "conftest.py").write_text(CONFTEST)
    (dest / "pytest.ini").write_text(PYTEST_INI)
    (dest / "TASK.md").write_text(TASK_MD.format(pkg=domain))


def build(mut: Mutation, scratch: Path) -> Built:
    errors: list[str] = []
    work = scratch / mut.key
    copy_template(mut.domain, work)

    clean = run_pytest(work)
    if not clean.ok:
        errors.append(f"clean template does not pass: {clean.failed[:3]}")

    root_line = mutated_line(work, mut.edits[0])
    apply_edits(work, mut.edits)
    root_file = work / mut.file
    span = function_span(root_file, mut.function)
    broken = run_pytest(work)
    if not broken.failed:
        errors.append("mutation does not make any test fail")

    shapes: dict[str, str] = {}
    root_test = f"tests/test_{Path(mut.file).stem}.py"
    for shape in mut.shapes:
        if shape == "deep-call-chain":
            local = [t for t in broken.failed if t.startswith(root_test + "::")]
            if local or not broken.failed:
                errors.append(f"deep-call-chain: failures in {root_test}: {local}")
            else:
                files = sorted({t.split("::")[0] for t in broken.failed})
                shapes[shape] = f"failures only in {', '.join(files)}; bug in {mut.file}"
        elif shape == "one-root-many":
            n = len(broken.failed)
            if 3 <= n <= 8:
                shapes[shape] = f"{n} failing tests"
            else:
                errors.append(f"one-root-many: {n} failing tests (need 3-8)")
        elif shape == "misleading-surface":
            rel = mut.file
            inside = [
                t for t, site in broken.crash_sites.items()
                if site.split(":")[0] == rel and span[0] <= int(site.split(":")[1]) <= span[1]
            ]
            sites = sorted(set(broken.crash_sites.values()))
            if inside or not sites:
                errors.append(f"misleading-surface: crash inside root function for {inside or 'no crashes'}")
            else:
                shapes[shape] = f"crashes surface at {', '.join(sites[:3])}; defect in {mut.function}"
        elif shape == "regression-trap":
            trap_dir = scratch / f"{mut.key}--trap"
            shutil.copytree(work, trap_dir, ignore=IGNORE)
            try:
                apply_edits(trap_dir, mut.trap)
                trapped = run_pytest(trap_dir)
                fixed = sorted(set(broken.failed) - set(trapped.failed))
                regressed = sorted(set(trapped.failed) - set(broken.failed))
                if fixed and regressed:
                    shapes[shape] = f"tempting fix clears {len(fixed)} failure(s) but breaks {regressed[:2]}"
                else:
                    errors.append(f"regression-trap: trap fixed={fixed} regressed={regressed}")
            except ValueError as exc:
                errors.append(f"regression-trap: {exc}")
        else:
            errors.append(f"unknown shape {shape}")

    fixed_dir = scratch / f"{mut.key}--fixed"
    shutil.copytree(work, fixed_dir, ignore=IGNORE)
    apply_edits(fixed_dir, revert_edits(mut.edits))
    if not run_pytest(fixed_dir).ok:
        errors.append("reverting the mutation does not make the suite pass")

    return Built(mut, broken.failed, broken.passed, root_line, span, shapes, errors)


# ---------------------------------------------------------------- splits

def assign(built: list[Built]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Deterministically name tasks and assign full + core splits."""
    rng = random.Random(SEED)
    by_domain: dict[str, list[Built]] = {}
    for b in built:
        by_domain.setdefault(b.mutation.domain, []).append(b)

    ids: dict[str, str] = {}
    for domain in sorted(by_domain):
        items = sorted(by_domain[domain], key=lambda b: b.mutation.key)
        rng.shuffle(items)
        by_domain[domain] = items
        for i, b in enumerate(items, 1):
            ids[b.mutation.key] = f"{domain}-{i:02d}"

    sizes = PROFILES["full"]
    splits: dict[str, list[str]] = {"train": [], "gate": [], "heldout": []}
    pool: list[Built] = []
    for domain, items in sorted(by_domain.items()):
        for b in items:
            if domain == NOVEL_DOMAIN or b.mutation.pin_split == "heldout":
                splits["heldout"].append(ids[b.mutation.key])
            else:
                pool.append(b)
    # Stratify by bug shape: walk shapes in a fixed order and deal tasks out in a 12:6:6 pattern,
    # so every split sees every shape (the teacher must meet each failure kind in train).
    pattern = ["train", "gate", "train", "heldout"]
    by_shape: dict[str, list[Built]] = {}
    for b in pool:
        by_shape.setdefault(b.mutation.shapes[0], []).append(b)
    cursor = 0
    for shape in SHAPES:
        group = sorted(by_shape.get(shape, []), key=lambda b: ids[b.mutation.key])
        rng.shuffle(group)
        for b in group:
            for k in range(len(pattern)):
                split = pattern[(cursor + k) % len(pattern)]
                if len(splits[split]) < sizes[split]:
                    splits[split].append(ids[b.mutation.key])
                    cursor = (cursor + k + 1) % len(pattern)
                    break
            else:
                raise ValueError(f"too many tasks for profile full: {ids[b.mutation.key]}")
    return ids, splits


def core_profile(splits: dict[str, list[str]], index: dict[str, dict]) -> dict[str, list[str]]:
    """Small fast subset: 2 train domains, demo task + one novel-domain task in held-out."""
    want = PROFILES["core"]
    core: dict[str, list[str]] = {}
    priority = ("deep-call-chain", "regression-trap", "misleading-surface", "one-root-many")
    for split in ("train", "gate"):
        picked: list[str] = []
        pool = sorted(splits[split], key=lambda t: (index[t]["domain"] != "ledgerly", t))
        # one task per process-heavy shape first, in priority order
        for shape in priority:
            match = next((t for t in pool if t not in picked and shape in index[t]["shapes"]), None)
            if match and len(picked) < want[split]:
                picked.append(match)
        picked += [t for t in pool if t not in picked][: want[split] - len(picked)]
        core[split] = picked
    held = [t for t in splits["heldout"] if index[t].get("demo")]
    held += [t for t in splits["heldout"] if index[t]["domain"] == NOVEL_DOMAIN][:1]
    held += [t for t in splits["heldout"] if t not in held and index[t]["domain"] == "ledgerly"]
    held += [t for t in splits["heldout"] if t not in held]
    core["heldout"] = held[: want["heldout"]]
    return core


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify only; write nothing")
    ap.add_argument("--only", help="comma-separated mutation keys")
    args = ap.parse_args(argv)

    muts = [m for m in MUTATIONS if not args.only or m.key in args.only.split(",")]
    built: list[Built] = []
    with tempfile.TemporaryDirectory(prefix="manifest-gen-") as tmp:
        for mut in muts:
            b = build(mut, Path(tmp))
            built.append(b)
            status = "OK " if not b.errors else "BAD"
            print(f"{status} {mut.domain:10} {mut.key:22} {len(b.failing):2} failing  {','.join(mut.shapes)}")
            for shape, ev in b.shapes_ok.items():
                print(f"      ✓ {shape}: {ev}")
            for err in b.errors:
                print(f"      ✗ {err}")
    demo_built: list[Built] = []
    if not args.only:
        with tempfile.TemporaryDirectory(prefix="manifest-gen-demo-") as tmp:
            for mut in DEMO_MUTATIONS:
                b = build(mut, Path(tmp))
                demo_built.append(b)
                print(f"{'OK ' if not b.errors else 'BAD'} {mut.domain:10} {mut.key:22} {len(b.failing):2} failing  "
                      f"{','.join(mut.shapes)}  [demo]")
                for err in b.errors:
                    print(f"      ✗ {err}")
    bad = [b for b in built + demo_built if b.errors]
    if bad:
        print(f"\n{len(bad)} mutation(s) failed verification")
        return 1
    if args.check or args.only:
        return 0

    ids, splits = assign(built)
    # demo tasks take the next free number in their domain, so every scored task keeps its id
    per_domain = {}
    for b in built:
        per_domain[b.mutation.domain] = per_domain.get(b.mutation.domain, 0) + 1
    demo_ids = []
    for b in demo_built:
        per_domain[b.mutation.domain] += 1
        ids[b.mutation.key] = f"{b.mutation.domain}-{per_domain[b.mutation.domain]:02d}"
        demo_ids.append(ids[b.mutation.key])
    split_of = {tid: s for s, tids in splits.items() for tid in tids}
    split_of.update({tid: "demo" for tid in demo_ids})
    index: dict[str, dict] = {}
    if GENERATED.exists():
        shutil.rmtree(GENERATED)
    GENERATED.mkdir(parents=True)
    for b in sorted(built + demo_built, key=lambda b: ids[b.mutation.key]):
        tid = ids[b.mutation.key]
        dest = GENERATED / tid
        copy_template(b.mutation.domain, dest)
        apply_edits(dest, b.mutation.edits)
        index[tid] = {
            "domain": b.mutation.domain,
            "bugShape": b.mutation.shapes[0],
            "shapes": list(b.mutation.shapes),
            "mutation": b.mutation.operator,
            "mutationKey": b.mutation.key,
            "split": split_of[tid],
            "demo": b.mutation.pin_split == "heldout" or split_of[tid] == "demo",
            "rootCause": {"file": b.mutation.file, "function": b.mutation.function, "line": b.root_line,
                          "span": list(b.span)},
            "failingTests": b.failing,
            "passingTests": len(b.passing),
            "evidence": b.shapes_ok,
            "fix": [e.__dict__ for e in revert_edits(b.mutation.edits)],
            "trap": [e.__dict__ for e in b.mutation.trap],
            "note": b.mutation.note,
        }
    profiles = {"full": splits, "core": core_profile(splits, index)}
    hero = [t for t, m in index.items() if m["demo"] and m["split"] == "heldout"]
    # live demo: none of these were ever seen by the teacher (hero = scored held-out task, rest = demo-only)
    profiles["demo"] = {"train": [], "gate": [], "heldout": hero + demo_ids}
    (ROOT / "splits.json").write_text(json.dumps(
        {"seed": SEED, "novelDomain": NOVEL_DOMAIN, **splits, "profiles": profiles}, indent=2) + "\n")
    (ROOT / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(f"\nwrote {len(index)} tasks → {GENERATED.relative_to(ROOT.parent)}")
    for name, prof in profiles.items():
        print(f"  {name:5} " + "  ".join(f"{s}={len(t)}" for s, t in prof.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
