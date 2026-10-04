import pytest

from gradebook.weights import WeightError, normalize


def test_normalize_sums_to_one():
    w = normalize({"hw": 30, "exam": 70})
    assert w == {"hw": 0.3, "exam": 0.7}


def test_zero_weight_category_is_kept():
    assert normalize({"hw": 0, "exam": 50}) == {"hw": 0.0, "exam": 1.0}


def test_bad_weights_are_rejected():
    with pytest.raises(WeightError):
        normalize({"hw": -1, "exam": 2})
    with pytest.raises(WeightError):
        normalize({"hw": 0, "exam": 0})
