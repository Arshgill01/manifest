import pytest

from gradebook.scores import Score, drop_lowest, mean_percent


def test_raw_and_late_percent():
    s = Score("hw1", 45, 50, days_late=2)
    assert s.raw_percent() == 90.0
    assert s.percent() == 70.0


def test_very_late_work_scores_zero():
    assert Score("hw1", 50, 50, days_late=6).percent() == 0.0
    assert Score("hw1", 50, 50, days_late=5).percent() == 50.0


def test_penalty_never_goes_below_zero():
    assert Score("hw1", 10, 50, days_late=3).percent() == 0.0


def test_drop_lowest_keeps_order_and_breaks_ties_by_position():
    scores = [Score("a", 8, 10), Score("b", 5, 10), Score("c", 5, 10), Score("d", 9, 10)]
    assert [s.name for s in drop_lowest(scores, 1)] == ["a", "c", "d"]
    assert [s.name for s in drop_lowest(scores, 10)] == ["d"]


def test_invalid_scores_are_rejected():
    with pytest.raises(ValueError):
        Score("x", 11, 10)
    with pytest.raises(ValueError):
        Score("x", 1, 0)
    with pytest.raises(ValueError):
        mean_percent([])


def test_mean_percent_uses_penalised_scores():
    assert mean_percent([Score("a", 10, 10), Score("b", 10, 10, days_late=4)]) == 80.0
