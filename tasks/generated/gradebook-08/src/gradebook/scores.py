"""Individual scores: percentages, late penalties, dropping the lowest."""

from __future__ import annotations

from dataclasses import dataclass

LATE_PENALTY_PER_DAY = 10.0   # percentage points
MAX_LATE_DAYS = 5             # after this the work scores zero


@dataclass(frozen=True)
class Score:
    name: str
    earned: float
    possible: float
    days_late: int = 0

    def __post_init__(self):
        if self.possible <= 0:
            raise ValueError(f"{self.name}: possible points must be positive")
        if not 0 <= self.earned <= self.possible:
            raise ValueError(f"{self.name}: earned {self.earned} outside 0..{self.possible}")
        if self.days_late < 0:
            raise ValueError(f"{self.name}: days late cannot be negative")

    def raw_percent(self) -> float:
        return 100.0 * self.earned / self.possible

    def percent(self) -> float:
        """Percentage after the late penalty (never below zero)."""
        if self.days_late >= MAX_LATE_DAYS:
            return 0.0
        return max(0.0, self.raw_percent() - LATE_PENALTY_PER_DAY * self.days_late)


def drop_lowest(scores: list[Score], n: int) -> list[Score]:
    """Remove the n lowest-percentage scores (ties: the earliest one goes first). Keeps at least one."""
    if n < 0:
        raise ValueError("cannot drop a negative number of scores")
    keep = max(1, len(scores) - n)
    ranked = sorted(range(len(scores)), key=lambda i: (scores[i].percent(), i))
    dropped = set(ranked[: len(scores) - keep])
    return [s for i, s in enumerate(scores) if i not in dropped]


def mean_percent(scores: list[Score]) -> float:
    if not scores:
        raise ValueError("no scores")
    return sum(s.percent() for s in scores) / len(scores)
