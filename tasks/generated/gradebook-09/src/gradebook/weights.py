"""Category weights (e.g. homework 30, exams 70) and weighted averages."""

from __future__ import annotations


class WeightError(ValueError):
    pass


def normalize(weights: dict[str, float]) -> dict[str, float]:
    """Scale weights so they sum to 1. Zero-weight categories are kept (they just don't count)."""
    if any(w <= 0 for w in weights.values()):
        raise WeightError("weights cannot be negative")
    total = sum(weights.values())
    if total <= 0:
        raise WeightError("weights must sum to a positive number")
    return {k: w / total for k, w in weights.items()}


def weighted_average(values: dict[str, float], weights: dict[str, float]) -> float:
    """Average of `values` by `weights`; categories without a value are left out and the rest re-weighted."""
    present = {k: w for k, w in weights.items() if k in values}
    if not present:
        raise WeightError("no graded category")
    norm = normalize(present)
    return sum(values[k] * norm[k] for k in norm)
