from datetime import date

import pytest

from csvflow.schema import BadValue, Column, coerce


def test_numbers_and_dates():
    assert coerce(Column("n", "int"), " 42 ") == 42
    assert coerce(Column("x", "float"), "2.5") == 2.5
    assert coerce(Column("d", "date"), "2026-01-03") == date(2026, 1, 3)


def test_booleans():
    col = Column("b", "bool")
    assert [coerce(col, v) for v in ("yes", "TRUE", "0", "n")] == [True, True, False, False]
    with pytest.raises(BadValue):
        coerce(col, "maybe")


def test_required_and_defaults():
    with pytest.raises(BadValue):
        coerce(Column("n", "int"), "  ")
    assert coerce(Column("n", "int", required=False, default=7), "") == 7


def test_bad_values():
    with pytest.raises(BadValue):
        coerce(Column("n", "int"), "4.2")
    with pytest.raises(BadValue):
        coerce(Column("n", "uuid"), "x")
