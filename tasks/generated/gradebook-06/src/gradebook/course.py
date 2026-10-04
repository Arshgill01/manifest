"""A course: categories with weights, scores per student, final percentages and letters."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .scale import DEFAULT_SCALE, letter
from .scores import Score, drop_lowest, mean_percent
from .weights import weighted_average


class UnknownCategory(KeyError):
    pass


@dataclass
class Category:
    name: str
    weight: float
    drop: int = 0


@dataclass
class Course:
    code: str
    credits: float
    categories: dict[str, Category] = field(default_factory=dict)
    scale: tuple = DEFAULT_SCALE
    _scores: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(list)))

    def add_category(self, name: str, weight: float, drop: int = 0) -> "Course":
        self.categories[name] = Category(name, weight, drop)
        return self

    def record(self, student: str, category: str, score: Score) -> None:
        if category not in self.categories:
            raise UnknownCategory(category)
        self._scores[student][category].append(score)

    def students(self) -> list[str]:
        return sorted(self._scores)

    def category_percent(self, student: str, category: str) -> float | None:
        scores = self._scores[student].get(category, [])
        if not scores:
            return None
        return mean_percent(drop_lowest(scores, self.categories[category].drop))

    def percent(self, student: str) -> float:
        values = {}
        for name in self.categories:
            p = self.category_percent(student, name)
            if p is not None:
                values[name] = p
        weights = {name: c.weight for name, c in self.categories.items()}
        return round(weighted_average(values, weights), 2)

    def letter(self, student: str) -> str:
        return letter(self.percent(student), self.scale)
