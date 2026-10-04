"""Row transforms."""

from __future__ import annotations

from typing import Any, Callable


def rename(rows: list[dict], mapping: dict[str, str]) -> list[dict]:
    return [{mapping.get(k, k): v for k, v in row.items()} for row in rows]


def derive(rows: list[dict], name: str, fn: Callable[[dict], Any]) -> list[dict]:
    return [{**row, name: fn(row)} for row in rows]


def filter_rows(rows: list[dict], predicate: Callable[[dict], bool]) -> list[dict]:
    return [row for row in rows if predicate(row)]


def dedupe(rows: list[dict], keys: list[str]) -> list[dict]:
    """Drop rows whose key columns repeat an earlier row; the first one wins."""
    seen = set()
    out = []
    for row in rows:
        key = tuple(row[k] for k in keys)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out
