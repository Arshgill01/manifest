from datetime import time

import pytest

from slotbook.resources import Directory, Room, UnknownRoom, opening_hours

from .helpers import DAY, make_calendar, rng, utc


def test_opening_hours_for_custom_room():
    assert opening_hours(Room("Late", 2, opens=time(12), closes=time(20)), DAY) == rng(12, 0, 20, 0)


def test_opening_hours_are_room_local():
    hours = opening_hours(Room("Pune", 6, zone="IST", opens=time(9), closes=time(18)), DAY)
    assert (hours.start, hours.end) == (utc(3, 30), utc(12, 30))


def test_rooms_with_capacity_smallest_first():
    rooms = make_calendar().directory.rooms_with_capacity(6)
    assert [r.name for r in rooms] == ["Kochi", "Borealis"]
    assert make_calendar().directory.rooms_with_capacity(9) == []


def test_room_validation():
    with pytest.raises(ValueError):
        Directory([Room("Closet", 0)])
    with pytest.raises(UnknownRoom):
        make_calendar().directory.get("Nowhere")
