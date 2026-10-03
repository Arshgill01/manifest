"""Token bucket: bursts up to `capacity`, refills continuously at `rate` tokens/second."""

from __future__ import annotations

from fractions import Fraction


class TokenBucket:
    def __init__(self, capacity: int, rate, clock):
        if capacity <= 0 or rate <= 0:
            raise ValueError("capacity and rate must be positive")
        self.capacity = capacity
        self.rate = Fraction(rate)
        self.clock = clock
        self.tokens = Fraction(capacity)
        self.updated = clock.now()

    def _refill(self) -> None:
        now = self.clock.now()
        elapsed = max(0, now - self.updated)
        self.tokens = min(Fraction(self.capacity), self.tokens + elapsed * self.rate)
        self.updated = now

    def available(self) -> Fraction:
        self._refill()
        return self.tokens

    def try_take(self, n: int = 1) -> bool:
        if n > self.capacity:
            raise ValueError(f"cannot take {n} tokens from a bucket of {self.capacity}")
        self._refill()
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def wait_time(self, n: int = 1) -> Fraction:
        """Seconds until `n` tokens are available (0 if they already are)."""
        self._refill()
        deficit = n - self.tokens
        if deficit <= 0:
            return Fraction(0)
        return self.rate / deficit
