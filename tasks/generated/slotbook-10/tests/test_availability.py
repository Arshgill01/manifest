from slotbook.availability import find_slot, free_slots
from slotbook.timerange import TimeRange

from .helpers import DAY, ist, make_calendar, rng


def test_empty_day_is_all_free():
    assert free_slots(make_calendar(), "Atlas", DAY, 30) == [rng(9, 0, 18, 0)]


def test_free_slots_around_bookings():
    cal = make_calendar()
    cal.book("Atlas", rng(9, 30, 11, 0), 2, "ana")
    cal.book("Atlas", rng(15, 0, 15, 20), 2, "ben")
    assert free_slots(cal, "Atlas", DAY, 30) == [rng(9, 0, 9, 30), rng(11, 0, 15, 0), rng(15, 20, 18, 0)]
    assert free_slots(cal, "Atlas", DAY, 45) == [rng(11, 0, 15, 0), rng(15, 20, 18, 0)]


def test_find_slot_is_earliest_across_zones():
    cal = make_calendar()
    assert find_slot(cal, DAY, 60, 4) == ("Kochi", TimeRange(ist(9), ist(10)))
    assert find_slot(cal, DAY, 60, 7) == ("Borealis", rng(9, 0, 10, 0))


def test_find_slot_skips_busy_rooms():
    cal = make_calendar()
    cal.book("Kochi", TimeRange(ist(9), ist(18)), 2, "devi")
    cal.book("Atlas", rng(9, 0, 12, 0), 2, "ana")
    cal.book("Borealis", rng(9, 0, 10, 0), 2, "ben")
    assert find_slot(cal, DAY, 60, 4) == ("Borealis", rng(10, 0, 11, 0))


def test_no_room_big_enough():
    assert find_slot(make_calendar(), DAY, 30, 9) is None
