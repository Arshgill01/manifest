import pytest

from slotbook.bookings import Conflict, OutsideHours, OverCapacity, UnknownBooking
from slotbook.timerange import TimeRange

from .helpers import ist, make_calendar, rng, utc


def test_book_room():
    cal = make_calendar()
    b = cal.book("Atlas", rng(9, 0, 10, 0), 3, "ana")
    assert b.id == "B001"
    assert cal.bookings_for("Atlas") == [b]


def test_overlapping_booking_conflicts():
    cal = make_calendar()
    cal.book("Atlas", rng(9, 0, 10, 0), 3, "ana")
    with pytest.raises(Conflict):
        cal.book("Atlas", rng(9, 30, 10, 30), 2, "ben")


def test_back_to_back_bookings_allowed():
    cal = make_calendar()
    cal.book("Atlas", rng(9, 0, 10, 0), 3, "ana")
    cal.book("Atlas", rng(10, 0, 11, 0), 3, "ben")
    assert len(cal.bookings_for("Atlas")) == 2


def test_outside_opening_hours():
    cal = make_calendar()
    with pytest.raises(OutsideHours):
        cal.book("Atlas", rng(8, 30, 9, 30), 2, "ana")
    with pytest.raises(OutsideHours):
        cal.book("Atlas", rng(17, 30, 18, 30), 2, "ana")


def test_last_hour_of_the_day():
    cal = make_calendar()
    assert cal.book("Atlas", rng(17, 0, 18, 0), 2, "ana").id == "B001"


def test_capacity():
    cal = make_calendar()
    with pytest.raises(OverCapacity):
        cal.book("Atlas", rng(9, 0, 10, 0), 5, "ana")
    cal.book("Atlas", rng(9, 0, 10, 0), 4, "ana")


def test_room_in_another_zone_uses_local_hours():
    cal = make_calendar()
    cal.book("Kochi", TimeRange(ist(9), ist(10)), 6, "devi")
    with pytest.raises(OutsideHours):
        cal.book("Kochi", TimeRange(utc(13), utc(14)), 2, "devi")


def test_cancel_frees_the_slot():
    cal = make_calendar()
    b = cal.book("Atlas", rng(9, 0, 10, 0), 3, "ana")
    cal.cancel(b.id)
    cal.book("Atlas", rng(9, 0, 10, 0), 3, "ben")
    with pytest.raises(UnknownBooking):
        cal.cancel(b.id)
