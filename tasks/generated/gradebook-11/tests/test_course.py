import pytest

from gradebook.course import Course, UnknownCategory
from gradebook.scores import Score

from .helpers import course_with_two_students


def test_weighted_percent_with_drop_lowest():
    c = course_with_two_students()
    # hw: drop the 6 -> mean(100, 80) = 90; exam: mean(80, 90) = 85; 0.3*90 + 0.7*85 = 86.5
    assert c.percent("ana") == 86.5


def test_letter_from_percent():
    c = course_with_two_students()
    assert c.letter("ana") == "B"
    assert c.percent("ben") == 57.0     # hw: one score, nothing dropped (keeps at least one) -> 0.3*50 + 0.7*60
    assert c.letter("ben") == "F"


def test_missing_category_is_reweighted():
    c = Course("X", 3).add_category("hw", 30).add_category("exam", 70)
    c.record("cy", "hw", Score("h1", 9, 10))
    assert c.percent("cy") == 90.0


def test_unknown_category_is_rejected():
    c = Course("X", 3).add_category("hw", 100)
    with pytest.raises(UnknownCategory):
        c.record("cy", "lab", Score("l1", 1, 1))


def test_students_sorted_and_late_penalty_flows_through():
    c = Course("X", 3).add_category("hw", 100)
    c.record("zed", "hw", Score("h1", 10, 10, days_late=1))
    c.record("amy", "hw", Score("h1", 10, 10))
    assert c.students() == ["amy", "zed"]
    assert c.percent("zed") == 90.0


def test_percent_is_rounded_to_two_places():
    c = Course("X", 3).add_category("hw", 1).add_category("exam", 2)
    c.record("di", "hw", Score("h1", 1, 3))
    c.record("di", "exam", Score("e1", 2, 3))
    assert c.percent("di") == 55.56
