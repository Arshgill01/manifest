import pytest

from slotbook.zones import UnknownZone, local_day, to_zone, wall_clock

from .helpers import DAY, ist, utc


def test_ist_is_five_thirty_ahead():
    assert to_zone(ist(9), "UTC") == utc(3, 30)
    assert wall_clock(utc(9), "IST") == "14:30"


def test_western_zones():
    assert wall_clock(utc(9), "PST") == "01:00"
    assert wall_clock(utc(9), "EST") == "04:00"


def test_unknown_zone():
    with pytest.raises(UnknownZone):
        wall_clock(utc(9), "MARS")


def test_local_day_bounds():
    day = local_day("IST", DAY)
    assert day.start == utc(18, 30, d=1)
    assert day.minutes() == 24 * 60
