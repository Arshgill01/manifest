"""Room bookings with conflict, capacity and opening-hours checks."""

from __future__ import annotations

from dataclasses import dataclass

from .resources import Directory, Room, opening_hours
from .timerange import TimeRange
from .zones import to_zone


class BookingError(ValueError):
    pass


class Conflict(BookingError):
    pass


class OutsideHours(BookingError):
    pass


class OverCapacity(BookingError):
    pass


class UnknownBooking(KeyError):
    pass


@dataclass(frozen=True)
class Booking:
    id: str
    room: str
    when: TimeRange
    attendees: int
    owner: str


class Calendar:
    def __init__(self, directory: Directory):
        self.directory = directory
        self._bookings: dict[str, Booking] = {}
        self._seq = 0

    def bookings_for(self, room: str, window: TimeRange | None = None) -> list[Booking]:
        found = [b for b in self._bookings.values() if b.room == room and (window is None or b.when.overlaps(window))]
        return sorted(found, key=lambda b: b.when.start)

    def check(self, room_name: str, when: TimeRange, attendees: int) -> Room:
        room = self.directory.get(room_name)
        if attendees > room.capacity:
            raise OverCapacity(f"{room_name} holds {room.capacity}, asked for {attendees}")
        local_day = to_zone(when.start, room.zone).date()
        hours = opening_hours(room, local_day)
        if not (hours.start <= when.start and when.end <= hours.end):
            raise OutsideHours(f"{room_name} is open {hours.start:%H:%M}-{hours.end:%H:%M} {room.zone}")
        for existing in self.bookings_for(room_name):
            if existing.when.overlaps(when):
                raise Conflict(f"{room_name} is already booked by {existing.owner} ({existing.id})")
        return room

    def book(self, room_name: str, when: TimeRange, attendees: int, owner: str) -> Booking:
        self.check(room_name, when, attendees)
        self._seq += 1
        booking = Booking(f"B{self._seq:03d}", room_name, when, attendees, owner)
        self._bookings[booking.id] = booking
        return booking

    def cancel(self, booking_id: str) -> Booking:
        try:
            return self._bookings.pop(booking_id)
        except KeyError:
            raise UnknownBooking(booking_id) from None
