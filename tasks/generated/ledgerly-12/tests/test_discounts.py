from decimal import Decimal

import pytest

from ledgerly.discounts import InvalidCoupon, coupon_discount, percent_off, spread, volume_percent
from ledgerly.money import Money


def m(s):
    return Money(Decimal(s))


def test_volume_tiers_start_at_threshold():
    assert volume_percent(10) == Decimal("5")
    assert volume_percent(50) == Decimal("10")
    assert volume_percent(100) == Decimal("15")


def test_volume_below_and_between_tiers():
    assert volume_percent(9) == Decimal("0")
    assert volume_percent(49) == Decimal("5")
    assert volume_percent(250) == Decimal("15")


def test_percent_off():
    assert percent_off(m("80.00"), 25) == m("20.00")
    with pytest.raises(ValueError):
        percent_off(m("80.00"), 120)


def test_coupons():
    assert coupon_discount(m("200.00"), "WELCOME10") == m("20.00")
    assert coupon_discount(m("200.00"), "flat5") == m("5.00")
    assert coupon_discount(m("30.00"), "BIGSPENDER") == m("30.00")
    with pytest.raises(InvalidCoupon):
        coupon_discount(m("30.00"), "NOPE")


def test_spread_is_proportional_and_keeps_every_cent():
    shares = spread(m("1.00"), [m("1"), m("2"), m("4")])
    assert shares == [m("0.14"), m("0.29"), m("0.57")]
    assert sum(s.amount for s in shares) == Decimal("1.00")


def test_spread_nothing():
    assert spread(m("5.00"), []) == []
