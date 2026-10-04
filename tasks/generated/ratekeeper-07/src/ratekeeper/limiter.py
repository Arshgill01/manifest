"""Per-key API rate limiter: token bucket for bursts + daily quota."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .bucket import TokenBucket
from .quota import DailyQuota, Plan, get_plan


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: Fraction
    remaining_today: int
    reason: str = ""


class RateLimiter:
    def __init__(self, clock):
        self.clock = clock
        self._buckets: dict[str, TokenBucket] = {}
        self._quotas: dict[str, DailyQuota] = {}

    def _state(self, key: str, plan: Plan) -> tuple[TokenBucket, DailyQuota]:
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(plan.burst, Fraction(60, plan.per_minute), self.clock)
            self._quotas[key] = DailyQuota(plan.per_day, self.clock)
        return self._buckets[key], self._quotas[key]

    def check(self, key: str, plan_name: str, cost: int = 1) -> Decision:
        """Decide whether `key` may spend `cost` units now; records the spend if allowed."""
        plan = get_plan(plan_name)
        bucket, quota = self._state(key, plan)
        if quota.remaining() < cost:
            return Decision(False, quota.seconds_until_reset(), quota.remaining(), "daily quota")
        if not bucket.try_take(cost):
            return Decision(False, bucket.wait_time(cost), quota.remaining(), "rate")
        quota.consume(cost)
        return Decision(True, Fraction(0), quota.remaining())
