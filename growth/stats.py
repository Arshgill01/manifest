"""Small, dependency-free statistics for RESULTS.md (SPEC §3.6).

- task-level bootstrap CIs (10 000 resamples, fixed seed) for success rate and per-task means, as the paper;
- paired comparisons of two harnesses on the same tasks: mean difference with a paired bootstrap CI,
  discordant counts and an exact two-sided McNemar test.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Sequence

N_BOOT = 10_000
SEED = 1337


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def bootstrap_ci(xs: Sequence[float], stat: Callable[[Sequence[float]], float] = mean, *, n: int = N_BOOT,
                 alpha: float = 0.05, seed: int = SEED) -> tuple[float, float, float]:
    """(point, lo, hi) percentile CI of `stat` over resampled tasks."""
    xs = list(xs)
    if not xs:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    k = len(xs)
    boots = sorted(stat([xs[rng.randrange(k)] for _ in range(k)]) for _ in range(n))
    lo = boots[int(alpha / 2 * n)]
    hi = boots[min(n - 1, int((1 - alpha / 2) * n))]
    return stat(xs), lo, hi


def success_ci(passes: Sequence[bool], **kw) -> tuple[float, float, float]:
    return bootstrap_ci([1.0 if p else 0.0 for p in passes], **kw)


def paired_ci(a: dict[str, float], b: dict[str, float], **kw) -> tuple[float, float, float, int]:
    """Mean of (b - a) over the tasks both have, with a paired bootstrap CI. Returns (diff, lo, hi, n)."""
    common = sorted(set(a) & set(b))
    diffs = [float(b[t]) - float(a[t]) for t in common]
    d, lo, hi = bootstrap_ci(diffs, **kw)
    return d, lo, hi, len(common)


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def discordant(a: dict[str, bool], b: dict[str, bool]) -> tuple[int, int, int, int]:
    """(both pass, only a, only b, neither) over the common tasks."""
    common = set(a) & set(b)
    both = sum(1 for t in common if a[t] and b[t])
    oa = sum(1 for t in common if a[t] and not b[t])
    ob = sum(1 for t in common if b[t] and not a[t])
    return both, oa, ob, len(common) - both - oa - ob


def fmt_ci(point: float, lo: float, hi: float, *, pct: bool = False, digits: int = 1) -> str:
    if math.isnan(point):
        return "–"
    if pct:
        return f"{100 * point:.0f}% [{100 * lo:.0f}, {100 * hi:.0f}]"
    return f"{point:.{digits}f} [{lo:.{digits}f}, {hi:.{digits}f}]"
