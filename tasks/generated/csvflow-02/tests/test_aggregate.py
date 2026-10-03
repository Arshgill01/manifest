import pytest

from csvflow.aggregate import group_by, median, summarize


def test_group_by_preserves_order():
    rows = [{"k": "b", "v": 1}, {"k": "a", "v": 2}, {"k": "b", "v": 3}]
    assert group_by(rows, "k") == {"b": [rows[0], rows[2]], "a": [rows[1]]}


def test_median():
    assert median([3, 1, 2]) == 2
    assert median([4, 1, 3, 2]) == 2.5
    with pytest.raises(ValueError):
        median([])


def test_summarize_sorted_by_key():
    rows = [{"k": "b", "v": 1.0}, {"k": "a", "v": 2.0}, {"k": "b", "v": 4.0}]
    assert summarize(rows, "k", "v") == {
        "a": {"count": 1, "sum": 2.0, "mean": 2.0, "median": 2.0, "min": 2.0, "max": 2.0},
        "b": {"count": 2, "sum": 5.0, "mean": 2.5, "median": 2.5, "min": 1.0, "max": 4.0},
    }
