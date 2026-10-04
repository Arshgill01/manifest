"""Column types and value coercion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

TRUE = {"true", "yes", "y", "1"}
FALSE = {"false", "no", "n", "0"}


class BadValue(ValueError):
    pass


@dataclass(frozen=True)
class Column:
    name: str
    type: str = "str"
    required: bool = True
    default: Any = None


@dataclass(frozen=True)
class Schema:
    columns: tuple[Column, ...]

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.columns]


def coerce(column: Column, raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        if column.required:
            raise BadValue(f"{column.name} is required")
        return column.default
    try:
        if column.type == "str":
            return raw
        if column.type == "int":
            return int(raw)
        if column.type == "float":
            return float(raw)
        if column.type == "date":
            return date.fromisoformat(raw)
        if column.type == "bool":
            if raw.lower() in TRUE:
                return True
            if raw.lower() in FALSE:
                return False
            raise ValueError(raw)
    except ValueError:
        raise BadValue(f"{column.name}: {raw!r} is not a valid {column.type}") from None
    raise BadValue(f"{column.name}: unknown type {column.type!r}")
