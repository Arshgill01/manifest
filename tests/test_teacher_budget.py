"""Teacher spend control: peak schedule, price math, ledger, caps, off-peak waiting."""

from datetime import datetime, timezone

import pytest

from harness.budget import Budget, Ledger, PriceSchedule, Prices, TeacherBudgetExceeded, is_peak, next_offpeak


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_peak_windows_weekdays_only():
    assert is_peak(utc(2026, 10, 5, 1, 0))       # Monday 01:00 UTC
    assert not is_peak(utc(2026, 10, 5, 4, 0))   # end is exclusive
    assert is_peak(utc(2026, 10, 5, 9, 59))
    assert not is_peak(utc(2026, 10, 5, 12, 0))
    assert not is_peak(utc(2026, 10, 4, 2, 0))   # Sunday
    assert next_offpeak(utc(2026, 10, 5, 7, 30)) == utc(2026, 10, 5, 10, 0)


def test_peak_prices_are_double():
    s = PriceSchedule(Prices(0.15, 0.003, 0.60))
    assert s.prices(utc(2026, 10, 5, 2)).output == pytest.approx(1.20)
    assert s.prices(utc(2026, 10, 4, 2)).input_miss == pytest.approx(0.15)
    assert Prices(0.15, 0.003, 0.60).cost(10_000, 5_000, 4_000) == pytest.approx((6000 * .15 + 4000 * .003 + 5000 * .6) / 1e6)


def test_caps_and_ledger(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    b = Budget(run_cap=0.10, total_cap=1.0, ledger=led)
    b.before_call(estimate=0.05)
    b.record(cost=0.06, purpose="propose")
    assert led.total() == pytest.approx(0.06)
    with pytest.raises(TeacherBudgetExceeded, match="run cap"):
        b.before_call(estimate=0.05)
    b2 = Budget(total_cap=0.08, ledger=led)          # all-time cap sees the earlier run's spend
    with pytest.raises(TeacherBudgetExceeded, match="TEACHER_BUDGET_USD"):
        b2.before_call(estimate=0.05)


def test_offpeak_mode_waits(tmp_path, monkeypatch):
    import harness.budget as hb
    monkeypatch.setattr(hb, "is_peak", lambda now=None: True)
    monkeypatch.setattr(hb, "next_offpeak", lambda now=None: datetime.now(timezone.utc))
    slept = []
    b = Budget(total_cap=1.0, ledger=Ledger(tmp_path / "l.jsonl"), hours="offpeak", sleep=slept.append)
    b.before_call(estimate=0.01)
    assert slept and slept[0] >= 5


def test_real_teacher_gets_a_budget_by_default():
    from harness.log import EventLog
    from harness.teacher import Teacher
    t = Teacher(EventLog(), api_key="sk-test", model="deepseek-flash")   # builds a client, makes no call
    assert t.budget is not None
