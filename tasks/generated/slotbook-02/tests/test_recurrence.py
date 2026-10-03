from datetime import timedelta

import pytest

from slotbook.bookings import Conflict
from slotbook.recurrence import book_series, occurrences

from .helpers import make_calendar, rng, utc


def test_weekly_occurrences():
    starts = [r.start for r in occurrences(rng(9, 0, 10, 0), 3)]
    assert starts == [utc(9, d=2), utc(9, d=9), utc(9, d=16)]


def test_book_series():
    cal = make_calendar()
    cal.book("Atlas", rng(10, 0, 11, 0, d=9), 2, "ben")   # starts exactly when week 2 ends
    booked = book_series(cal, "Atlas", rng(9, 0, 10, 0), 3, 2, "ana")
    assert [b.id for b in booked] == ["B002", "B003", "B004"]


def test_series_is_all_or_nothing():
    cal = make_calendar()
    cal.book("Atlas", rng(9, 30, 10, 0, d=9), 2, "ben")
    with pytest.raises(Conflict):
        book_series(cal, "Atlas", rng(9, 0, 10, 0), 3, 2, "ana")
    assert len(cal.bookings_for("Atlas")) == 1


def test_series_validation_and_daily():
    with pytest.raises(ValueError):
        occurrences(rng(9, 0, 10, 0), 0)
    assert occurrences(rng(9, 0, 10, 0), 2, timedelta(days=1))[1].start == utc(9, d=3)
