"""Window-based limiters."""

from __future__ import annotations

from collections import deque


class SlidingWindowLog:
    """At most `limit` events in any trailing `window` seconds."""

    def __init__(self, limit: int, window, clock):
        self.limit = limit
        self.window = window
        self.clock = clock
        self.log: deque = deque()

    def _evict(self, now) -> None:
        while self.log and self.log[0] < now - self.window:
            self.log.popleft()

    def allow(self) -> bool:
        now = self.clock.now()
        self._evict(now)
        if len(self.log) < self.limit:
            self.log.append(now)
            return True
        return False

    def remaining(self) -> int:
        self._evict(self.clock.now())
        return self.limit - len(self.log)

    def reset_at(self):
        """When the oldest counted event stops counting."""
        self._evict(self.clock.now())
        return self.log[0] + self.window if self.log else self.clock.now()


class FixedWindowCounter:
    """At most `limit` events per aligned window [k*window, (k+1)*window)."""

    def __init__(self, limit: int, window, clock):
        self.limit = limit
        self.window = window
        self.clock = clock
        self.counts: dict = {}

    def window_start(self):
        return (self.clock.now() // self.window) * self.window

    def allow(self) -> bool:
        start = self.window_start()
        count = self.counts.get(start, 0)
        if count < self.limit:
            self.counts[start] = count + 1
            return True
        return False
