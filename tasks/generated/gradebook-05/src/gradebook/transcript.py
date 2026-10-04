"""Transcripts: credit-weighted GPA across courses, honours and standing."""

from __future__ import annotations

from dataclasses import dataclass, field

from .course import Course
from .scale import points


@dataclass(frozen=True)
class Entry:
    code: str
    credits: float
    letter: str


@dataclass
class Transcript:
    student: str
    entries: list[Entry] = field(default_factory=list)

    def add(self, course: Course, letter_override: str | None = None) -> Entry:
        entry = Entry(course.code, course.credits, letter_override or course.letter(self.student))
        self.entries.append(entry)
        return entry

    def credits(self) -> float:
        return sum(e.credits for e in self.entries)

    def gpa(self) -> float:
        """Credit-weighted grade points, rounded to 2 places (0.0 with no credits)."""
        total = self.credits()
        if total == 0:
            return 0.0
        return round(sum(points(e.letter) * e.credits for e in self.entries) / total, 2)

    def honours(self) -> str | None:
        g = self.gpa()
        if g >= 3.9:
            return "summa cum laude"
        if g >= 3.7:
            return "magna cum laude"
        if g >= 3.5:
            return "cum laude"
        return None

    def standing(self) -> str:
        return "probation" if self.credits() and self.gpa() < 2.0 else "good"
