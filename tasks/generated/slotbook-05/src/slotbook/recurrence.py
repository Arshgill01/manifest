"""Recurring bookings."""

from __future__ import annotations

from datetime import timedelta

from .bookings import Booking, Calendar
from .timerange import TimeRange


def occurrences(first: TimeRange, count: int, every: timedelta = timedelta(weeks=1)) -> list[TimeRange]:
    if count < 1:
        raise ValueError("a series needs at least one occurrence")
    return [first.shift(every * i) for i in range(count)]


def book_series(calendar: Calendar, room: str, first: TimeRange, count: int, attendees: int, owner: str,
                every: timedelta = timedelta(weeks=1)) -> list[Booking]:
    """Book every occurrence or none of them."""
    slots = occurrences(first, count, every)
    for slot in slots:
        calendar.check(room, slot, attendees)
    return [calendar.book(room, slot, attendees, owner) for slot in slots]
