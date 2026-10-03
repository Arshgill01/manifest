import pytest

from ratekeeper.clock import FakeClock
from ratekeeper.quota import DAY, DailyQuota, QuotaExceeded, UnknownPlan, get_plan


def test_plans():
    assert get_plan("free").burst == 5
    with pytest.raises(UnknownPlan):
        get_plan("platinum")


def test_consume_and_remaining():
    q = DailyQuota(3, FakeClock())
    q.consume(2)
    assert (q.used_today(), q.remaining()) == (2, 1)


def test_exceeding_quota_is_refused():
    q = DailyQuota(3, FakeClock())
    q.consume(2)
    with pytest.raises(QuotaExceeded):
        q.consume(2)
    assert q.used_today() == 2


def test_quota_resets_at_utc_midnight():
    clock = FakeClock(DAY - 10)
    q = DailyQuota(3, clock)
    q.consume(3)
    assert q.seconds_until_reset() == 10
    clock.advance(10)
    assert q.remaining() == 3
