from fractions import Fraction

import pytest

from ratekeeper.bucket import TokenBucket
from ratekeeper.clock import FakeClock


def bucket(clock):
    return TokenBucket(5, Fraction(1, 6), clock)   # 10 per minute, burst 5


def test_starts_full():
    assert bucket(FakeClock()).available() == 5


def test_take_until_empty():
    b = bucket(FakeClock())
    assert all(b.try_take() for _ in range(5))
    assert not b.try_take()


def test_refills_continuously():
    clock = FakeClock()
    b = bucket(clock)
    for _ in range(5):
        b.try_take()
    clock.advance(6)
    assert b.available() == 1
    clock.advance(3)
    assert b.available() == Fraction(3, 2)


def test_refill_capped_at_capacity():
    clock = FakeClock()
    b = bucket(clock)
    b.try_take(5)
    clock.advance(1000)
    assert b.available() == 5


def test_validation():
    with pytest.raises(ValueError):
        bucket(FakeClock()).try_take(6)
    with pytest.raises(ValueError):
        TokenBucket(0, 1, FakeClock())
