"""Plans and daily quotas (days are UTC, i.e. clock seconds // 86400)."""

from __future__ import annotations

from dataclasses import dataclass

DAY = 86400


@dataclass(frozen=True)
class Plan:
    name: str
    per_minute: int
    per_day: int
    burst: int


PLANS = {
    "free": Plan("free", per_minute=10, per_day=1000, burst=5),
    "pro": Plan("pro", per_minute=100, per_day=50_000, burst=50),
    "trial": Plan("trial", per_minute=60, per_day=3, burst=3),
}


class UnknownPlan(KeyError):
    pass


class QuotaExceeded(RuntimeError):
    pass


def get_plan(name: str) -> Plan:
    if name not in PLANS:
        raise UnknownPlan(name)
    return PLANS[name]


class DailyQuota:
    def __init__(self, limit: int, clock):
        self.limit = limit
        self.clock = clock
        self.used: dict[int, int] = {}

    def _day(self) -> int:
        return int(self.clock.now() // DAY)

    def used_today(self) -> int:
        return self.used.get(self._day(), 0)

    def remaining(self) -> int:
        return max(0, self.limit - self.used_today())

    def consume(self, n: int = 1) -> None:
        if n >= self.remaining():
            raise QuotaExceeded(f"daily quota of {self.limit} exhausted")
        day = self._day()
        self.used[day] = self.used.get(day, 0) + n

    def seconds_until_reset(self):
        return (self._day() + 1) * DAY - self.clock.now()
