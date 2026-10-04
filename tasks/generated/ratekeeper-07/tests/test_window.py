from ratekeeper.clock import FakeClock
from ratekeeper.window import FixedWindowCounter, SlidingWindowLog


def test_sliding_window_limit():
    w = SlidingWindowLog(3, 60, FakeClock())
    assert [w.allow() for _ in range(4)] == [True, True, True, False]


def test_sliding_window_frees_exactly_after_window():
    clock = FakeClock()
    w = SlidingWindowLog(3, 60, clock)
    for _ in range(3):
        w.allow()
    clock.advance(60)
    assert w.allow()


def test_sliding_window_evicts_oldest_only():
    clock = FakeClock()
    w = SlidingWindowLog(3, 60, clock)
    for t in (0, 20, 20):
        clock.advance(t)
        w.allow()
    clock.advance(19)   # t=59
    assert not w.allow()
    clock.advance(1)    # t=60: the t=0 event drops out
    assert w.allow()
    assert w.remaining() == 0


def test_remaining_and_reset():
    clock = FakeClock()
    w = SlidingWindowLog(3, 60, clock)
    w.allow()
    clock.advance(10)
    assert w.remaining() == 2
    assert w.reset_at() == 60


def test_fixed_window_resets_on_boundary():
    clock = FakeClock(59)
    w = FixedWindowCounter(2, 60, clock)
    assert [w.allow() for _ in range(3)] == [True, True, False]
    clock.advance(1)
    assert w.allow()
    assert w.window_start() == 60
