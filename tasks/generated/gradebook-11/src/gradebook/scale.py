"""Letter-grade scale: percentage cut-offs and grade points."""

from __future__ import annotations

from dataclasses import dataclass


class ScaleError(ValueError):
    pass


@dataclass(frozen=True)
class Band:
    letter: str
    minimum: float      # inclusive lower bound, in percent
    points: float


# Highest band first; the last band must start at 0 so every score has a letter.
DEFAULT_SCALE = (
    Band("A", 93.0, 4.0),
    Band("A-", 90.0, 3.7),
    Band("B+", 87.0, 3.3),
    Band("B", 83.0, 3.0),
    Band("B-", 80.0, 2.7),
    Band("C+", 77.0, 2.3),
    Band("C", 70.0, 2.0),
    Band("D", 60.0, 1.0),
    Band("F", 0.0, 0.0),
)


def check_scale(scale=DEFAULT_SCALE) -> None:
    mins = [b.minimum for b in scale]
    if mins != sorted(mins, reverse=True) or len(set(mins)) != len(mins):
        raise ScaleError("bands must be strictly decreasing")
    if mins[-1] != 0:
        raise ScaleError("the lowest band must start at 0")


def band_for(percent: float, scale=DEFAULT_SCALE) -> Band:
    if not 0 <= percent <= 100:
        raise ScaleError(f"percent out of range: {percent}")
    for band in scale:
        if percent >= band.minimum:
            return band
    raise ScaleError(f"no band for {percent}")


def letter(percent: float, scale=DEFAULT_SCALE) -> str:
    return band_for(percent, scale).letter


def points(letter_grade: str, scale=DEFAULT_SCALE) -> float:
    for band in scale:
        if band.letter == letter_grade:
            return band.points
    raise ScaleError(f"unknown letter {letter_grade!r}")
