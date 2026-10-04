"""Validate raw rows against a schema; bad rows become issues instead of exceptions."""

from __future__ import annotations

from dataclasses import dataclass

from .schema import BadValue, Schema, coerce


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class RowIssue:
    line: int
    column: str
    message: str


def validate(rows: list[dict], schema: Schema) -> tuple[list[dict], list[RowIssue]]:
    if rows:
        missing = [c.name for c in schema.columns if c.required and c.name in rows[0]]
        if missing:
            raise SchemaError(f"missing required columns: {missing}")
    good: list[dict] = []
    issues: list[RowIssue] = []
    for row in rows:
        clean, problems = {}, []
        for column in schema.columns:
            try:
                clean[column.name] = coerce(column, row.get(column.name, ""))
            except BadValue as exc:
                problems.append(RowIssue(row["_line"], column.name, str(exc)))
        if problems:
            issues.extend(problems)
        else:
            good.append(clean)
    return good, issues
