"""Bookable rooms."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from .timerange import TimeRange
from .zones import zone


class UnknownRoom(KeyError):
    pass


@dataclass(frozen=True)
class Room:
    name: str
    capacity: int
    zone: str = "UTC"
    opens: time = time(9)
    closes: time = time(18)


def opening_hours(room: Room, day: date) -> TimeRange:
    """The room's open window on a room-local calendar day."""
    tz = zone(room.zone)
    return TimeRange(datetime.combine(day, room.opens, tzinfo=tz), datetime.combine(day, room.closes, tzinfo=tz))


class Directory:
    def __init__(self, rooms=()):
        self._rooms: dict[str, Room] = {}
        for room in rooms:
            self.add(room)

    def add(self, room: Room) -> None:
        if room.capacity < 1:
            raise ValueError(f"{room.name}: capacity must be positive")
        self._rooms[room.name] = room

    def get(self, name: str) -> Room:
        if name not in self._rooms:
            raise UnknownRoom(name)
        return self._rooms[name]

    def rooms_with_capacity(self, people: int) -> list[Room]:
        """Rooms that fit `people`, smallest first."""
        fits = [r for r in self._rooms.values() if r.capacity >= people]
        return sorted(fits, key=lambda r: (r.capacity, r.name))
