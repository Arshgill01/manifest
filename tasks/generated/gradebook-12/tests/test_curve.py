from gradebook.course import Course
from gradebook.curve import curved, shift_needed
from gradebook.scores import Score


def test_shift_is_bounded():
    assert shift_needed([70, 80], 80) == 5.0
    assert shift_needed([90, 95], 80) == 0.0
    assert shift_needed([40, 50], 80) == 10.0
    assert shift_needed([], 80) == 0.0


def test_curve_caps_at_100():
    c = Course("X", 3).add_category("all", 1)
    c.record("a", "all", Score("t", 98, 100))
    c.record("b", "all", Score("t", 70, 100))
    assert curved(c, 90) == {"a": 100.0, "b": 76.0}


def test_curve_of_an_empty_course_is_empty():
    assert curved(Course("X", 3).add_category("all", 1), 80) == {}
