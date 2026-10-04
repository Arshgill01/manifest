from gradebook.course import Course
from gradebook.scores import Score
from gradebook.transcript import Transcript

from .helpers import course_with_two_students


def _course(code, credits, pct):
    c = Course(code, credits).add_category("all", 1)
    c.record("ana", "all", Score("t", pct, 100))
    return c


def test_gpa_is_credit_weighted():
    t = Transcript("ana")
    t.add(_course("A", 4, 95))   # A  4.0
    t.add(_course("B", 2, 85))   # B  3.0
    assert t.gpa() == round((4 * 4.0 + 2 * 3.0) / 6, 2)


def test_honours_bands():
    t = Transcript("ana")
    t.add(_course("A", 3, 95))
    assert t.honours() == "summa cum laude"
    t.add(_course("B", 1, 91))   # A- 3.7 -> (12 + 3.7) / 4 = 3.93
    assert t.honours() == "summa cum laude"
    t.add(_course("C", 4, 84))   # B 3.0 -> (15.7 + 12) / 8 = 3.46
    assert t.honours() is None


def test_standing_and_empty_transcript():
    t = Transcript("ana")
    assert t.gpa() == 0.0 and t.standing() == "good"
    t.add(_course("A", 3, 65))   # D 1.0
    assert t.standing() == "probation"


def test_letter_override_and_course_letters():
    t = Transcript("ana")
    e = t.add(course_with_two_students())
    assert e.letter == "B" and e.credits == 4
    t.add(_course("P", 1, 50), letter_override="A")
    assert t.gpa() == round((4 * 3.0 + 1 * 4.0) / 5, 2)
