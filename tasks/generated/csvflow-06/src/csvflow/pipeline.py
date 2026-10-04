"""End-to-end: text -> rows -> validated -> transformed -> summary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .aggregate import summarize
from .reader import read_rows
from .schema import Schema
from .transforms import dedupe, derive, filter_rows, rename
from .validate import RowIssue, validate


@dataclass
class Report:
    rows: list[dict]
    issues: list[RowIssue]
    summary: dict = field(default_factory=dict)


def run(text: str, schema: Schema, *, renames: dict[str, str] | None = None,
        derived: dict[str, Callable[[dict], Any]] | None = None, where: Callable[[dict], bool] | None = None,
        dedupe_on: list[str] | None = None, summarize_by: str | None = None,
        summarize_field: str | None = None) -> Report:
    rows = read_rows(text)
    if renames:
        rows = rename(rows, renames)
    good, issues = validate(rows, schema)
    for name, fn in (derived or {}).items():
        good = derive(good, name, fn)
    if where:
        good = filter_rows(good, where)
    if dedupe_on:
        good = dedupe(good, dedupe_on)
    summary = summarize(good, summarize_by, summarize_field) if summarize_by else {}
    return Report(good, issues, summary)
