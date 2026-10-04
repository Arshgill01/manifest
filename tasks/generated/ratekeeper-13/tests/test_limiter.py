import pytest

from ratekeeper.clock import FakeClock
from ratekeeper.limiter import RateLimiter
from ratekeeper.quota import UnknownPlan


def test_burst_then_rate_limited():
    rl = RateLimiter(FakeClock())
    assert all(rl.check("alice", "free").allowed for _ in range(5))
    denied = rl.check("alice", "free")
    assert (denied.allowed, denied.reason, denied.retry_after) == (False, "rate", 6)


def test_allowed_again_after_retry_after():
    clock = FakeClock()
    rl = RateLimiter(clock)
    for _ in range(5):
        rl.check("alice", "free")
    clock.advance(rl.check("alice", "free").retry_after)
    assert rl.check("alice", "free").allowed


def test_keys_are_isolated():
    rl = RateLimiter(FakeClock())
    for _ in range(6):
        rl.check("alice", "free")
    assert rl.check("bob", "free").allowed


def test_weighted_requests():
    rl = RateLimiter(FakeClock())
    assert all(rl.check("svc", "pro", cost=10).allowed for _ in range(5))
    denied = rl.check("svc", "pro", cost=10)
    assert not denied.allowed and denied.retry_after == 6


def test_daily_quota_blocks_until_midnight():
    clock = FakeClock(1000)
    rl = RateLimiter(clock)
    assert all(rl.check("t", "trial").allowed for _ in range(3))
    denied = rl.check("t", "trial")
    assert (denied.reason, denied.retry_after) == ("daily quota", 85400)
    clock.advance(85400)
    assert rl.check("t", "trial").allowed


def test_remaining_today_and_unknown_plan():
    rl = RateLimiter(FakeClock())
    assert rl.check("alice", "free").remaining_today == 999
    with pytest.raises(UnknownPlan):
        rl.check("alice", "gold")
