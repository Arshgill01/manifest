import pytest

from ratekeeper.clock import FakeClock


def test_fake_clock_moves_forward_only():
    clock = FakeClock(10)
    assert clock.advance(5) == 15
    with pytest.raises(ValueError):
        clock.advance(-1)
