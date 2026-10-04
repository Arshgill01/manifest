from datetime import datetime

import pytest

from slotbook.timerange import InvalidRange, TimeRange, gaps, merge

from .helpers import ist, rng, utc


def test_naive_datetimes_rejected():
    with pytest.raises(InvalidRange):
        TimeRange(datetime(2026, 3, 2, 9), datetime(2026, 3, 2, 10))


def test_empty_or_reversed_rejected():
    with pytest.raises(InvalidRange):
        rng(10, 0, 10, 0)
    with pytest.raises(InvalidRange):
        rng(11, 0, 10, 0)


def test_duration_and_contains():
    r = rng(9, 0, 10, 30)
    assert r.minutes() == 90
    assert r.contains(utc(9)) and not r.contains(utc(10, 30))


def test_overlap_rules():
    assert not rng(9, 0, 10, 0).overlaps(rng(10, 0, 11, 0))
    assert rng(9, 0, 10, 0).overlaps(rng(9, 30, 11, 0))
    assert TimeRange(ist(14, 30), ist(15, 30)).overlaps(rng(9, 30, 10, 30))


def test_intersection():
    assert rng(9, 0, 11, 0).intersection(rng(10, 0, 12, 0)) == rng(10, 0, 11, 0)
    assert rng(9, 0, 10, 0).intersection(rng(10, 0, 11, 0)) is None


def test_merge_joins_touching_and_overlapping():
    ranges = [rng(13, 30, 15, 0), rng(9, 0, 10, 0), rng(10, 0, 11, 0), rng(13, 0, 14, 0)]
    assert merge(ranges) == [rng(9, 0, 11, 0), rng(13, 0, 15, 0)]


def test_gaps_inside_window():
    busy = [rng(9, 0, 10, 0), rng(12, 0, 13, 0), rng(12, 30, 14, 0)]
    assert gaps(rng(9, 0, 18, 0), busy) == [rng(10, 0, 12, 0), rng(14, 0, 18, 0)]
