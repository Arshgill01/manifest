"""Grouping and summary statistics."""

from __future__ import annotations

from typing import Any


def group_by(rows: list[dict], key: str) -> dict[Any, list[dict]]:
    groups: dict[Any, list[dict]] = {}
    for row in rows:
        groups.setdefault(row[key], []).append(row)
    return groups


def median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median of nothing")
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def summarize(rows: list[dict], by: str, field: str) -> dict[Any, dict[str, float]]:
    out = {}
    for key, group in sorted(group_by(rows, by).items()):
        values = [row[field] for row in group]
        total = sum(values)
        out[key] = {
            "count": len(values),
            "sum": round(total, 2),
            "mean": round(total / len(values), 2),
            "median": median(values),
            "min": min(values),
            "max": max(values),
        }
    return out
