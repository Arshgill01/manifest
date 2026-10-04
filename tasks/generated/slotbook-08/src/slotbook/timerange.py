"""Half-open time ranges [start, end) over timezone-aware datetimes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable


class InvalidRange(ValueError):
    pass


@dataclass(frozen=True, order=True)
class TimeRange:
    start: datetime
    end: datetime

    def __post_init__(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise InvalidRange("time ranges need timezone-aware datetimes")
        if not self.start < self.end:
            raise InvalidRange(f"empty or reversed range {self.start} - {self.end}")

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def minutes(self) -> int:
        return int(self.duration.total_seconds() // 60)

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def overlaps(self, other: "TimeRange") -> bool:
        return self.start < other.end and other.start < self.end

    def intersection(self, other: "TimeRange") -> "TimeRange | None":
        start, end = min(self.start, other.start), max(self.end, other.end)
        return TimeRange(start, end) if start < end else None

    def shift(self, delta: timedelta) -> "TimeRange":
        return TimeRange(self.start + delta, self.end + delta)


def merge(ranges: Iterable[TimeRange]) -> list[TimeRange]:
    """Union of ranges; touching ranges are joined."""
    merged: list[TimeRange] = []
    for r in sorted(ranges):
        if merged and r.start <= merged[-1].end:
            merged[-1] = TimeRange(merged[-1].start, max(merged[-1].end, r.end))
        else:
            merged.append(r)
    return merged


def gaps(window: TimeRange, busy: Iterable[TimeRange]) -> list[TimeRange]:
    """Free parts of `window` not covered by any busy range."""
    free: list[TimeRange] = []
    cursor = window.start
    for r in merge(busy):
        if r.end <= cursor or r.start >= window.end:
            continue
        if r.start > cursor:
            free.append(TimeRange(cursor, r.start))
        cursor = max(cursor, r.end)
    if cursor < window.end:
        free.append(TimeRange(cursor, window.end))
    return free
