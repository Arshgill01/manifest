"""Fixed-offset time zones used by our offices (no DST in this product)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from .timerange import TimeRange

OFFSETS_MINUTES = {"UTC": 0, "IST": 330, "CET": 60, "EST": -300, "PST": -480}


class UnknownZone(KeyError):
    pass


def zone(name: str) -> timezone:
    try:
        return timezone(timedelta(minutes=-OFFSETS_MINUTES[name]), name)
    except KeyError:
        raise UnknownZone(name) from None


def at(name: str, y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=zone(name))


def to_zone(moment: datetime, name: str) -> datetime:
    return moment.astimezone(zone(name))


def local_day(name: str, day: date) -> TimeRange:
    start = datetime.combine(day, time(0), tzinfo=zone(name))
    return TimeRange(start, start + timedelta(days=1))


def wall_clock(moment: datetime, name: str) -> str:
    return to_zone(moment, name).strftime("%H:%M")
