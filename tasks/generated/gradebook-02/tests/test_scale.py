import pytest

from gradebook.scale import Band, ScaleError, band_for, check_scale, letter, points


def test_boundaries_are_inclusive_lower_bounds():
    assert letter(93.0) == "A"
    assert letter(92.99) == "A-"
    assert letter(70.0) == "C"
    assert letter(69.99) == "D"


def test_extremes():
    assert letter(100) == "A" and letter(0) == "F"


def test_out_of_range_is_rejected():
    with pytest.raises(ScaleError):
        band_for(100.5)
    with pytest.raises(ScaleError):
        band_for(-1)


def test_points_by_letter():
    assert points("B+") == 3.3 and points("F") == 0.0
    with pytest.raises(ScaleError):
        points("E")


def test_check_scale_rejects_bad_scales():
    check_scale()
    with pytest.raises(ScaleError):
        check_scale((Band("A", 90, 4), Band("B", 95, 3), Band("F", 0, 0)))
    with pytest.raises(ScaleError):
        check_scale((Band("A", 90, 4), Band("B", 80, 3)))
