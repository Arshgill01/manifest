"""Clocks. Everything takes a clock so limits are testable without sleeping."""

from __future__ import annotations

import time
from fractions import Fraction


class MonotonicClock:
    def now(self) -> float:
        return time.monotonic()


class FakeClock:
    def __init__(self, start=0):
        self._now = Fraction(start)

    def now(self) -> Fraction:
        return self._now

    def advance(self, seconds) -> Fraction:
        seconds = Fraction(seconds)
        if seconds < 0:
            raise ValueError("time only moves forward")
        self._now += seconds
        return self._now
