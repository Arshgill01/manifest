"""Curving: shift every final percentage so the class mean hits a target, capped at 100."""

from __future__ import annotations

from statistics import mean

from .course import Course

MAX_SHIFT = 10.0


def shift_needed(percents: list[float], target_mean: float) -> float:
    """Points to add to everyone (never negative, never above MAX_SHIFT)."""
    if not percents:
        return 0.0
    gap = target_mean - mean(percents)
    return max(MAX_SHIFT, max(0.0, gap))


def curved(course: Course, target_mean: float) -> dict[str, float]:
    finals = {s: course.percent(s) for s in course.students()}
    shift = shift_needed(list(finals.values()), target_mean)
    return {s: min(100.0, round(p + shift, 2)) for s, p in finals.items()}
