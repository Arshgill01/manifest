"""CSV ingest: normalised headers, one dict per record, record line numbers kept for error reports."""

from __future__ import annotations

import csv
import io


class RowError(ValueError):
    def __init__(self, line: int, message: str):
        super().__init__(f"line {line}: {message}")
        self.line = line


def normalize_header(name: str) -> str:
    return "_".join(name.strip().lower().split())


def read_rows(text: str, delimiter: str = ",") -> list[dict]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return []
    names = [normalize_header(h) for h in header]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate column names: {names}")
    rows = []
    for line, fields in enumerate(reader, start=2):
        if not fields or all(not f.strip() for f in fields):
            continue
        if len(fields) != len(names):
            raise RowError(line, f"expected {len(names)} fields, got {len(fields)}")
        row = dict(zip(names, fields))
        row["_line"] = line
        rows.append(row)
    return rows
