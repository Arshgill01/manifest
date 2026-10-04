from gradebook.course import Course
from gradebook.scores import Score


def course_with_two_students() -> Course:
    c = Course("CS101", credits=4).add_category("hw", 30, drop=1).add_category("exam", 70)
    for name, earned in (("h1", 10), ("h2", 6), ("h3", 8)):
        c.record("ana", "hw", Score(name, earned, 10))
    c.record("ana", "exam", Score("mid", 80, 100))
    c.record("ana", "exam", Score("final", 90, 100))
    c.record("ben", "hw", Score("h1", 5, 10))
    c.record("ben", "exam", Score("mid", 60, 100))
    return c
