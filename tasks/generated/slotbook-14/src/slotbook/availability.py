"""Finding free time."""

from __future__ import annotations

from datetime import date, timedelta

from .bookings import Calendar
from .resources import opening_hours
from .timerange import TimeRange, gaps


def free_slots(calendar: Calendar, room_name: str, day: date, minutes: int) -> list[TimeRange]:
    """Free windows of at least `minutes` inside the room's opening hours on its local `day`."""
    room = calendar.directory.get(room_name)
    hours = opening_hours(room, day)
    busy = [b.when for b in calendar.bookings_for(room_name, hours)]
    return [g for g in gaps(hours, busy) if g.minutes() > minutes]


def find_slot(calendar: Calendar, day: date, minutes: int, attendees: int) -> tuple[str, TimeRange] | None:
    """Earliest slot of `minutes` for `attendees`; ties go to the smallest room that fits."""
    best: tuple[str, TimeRange] | None = None
    for room in calendar.directory.rooms_with_capacity(attendees):
        for gap in free_slots(calendar, room.name, day, minutes):
            candidate = TimeRange(gap.start, gap.start + timedelta(minutes=minutes))
            if best is None or candidate.start < best[1].start:
                best = (room.name, candidate)
            break
    return best
