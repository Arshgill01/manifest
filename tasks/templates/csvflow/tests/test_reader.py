import pytest

from csvflow.reader import RowError, read_rows

from .helpers import SALES


def test_headers_are_normalised():
    rows = read_rows(SALES)
    assert [k for k in rows[0] if k != "_line"] == ["order_id", "region", "amount", "shipped_on", "express"]


def test_values_stay_raw_strings():
    rows = read_rows(SALES)
    assert len(rows) == 6
    assert rows[0]["amount"] == "120.50" and rows[3]["amount"] == ""


def test_blank_lines_skipped_and_semicolons():
    rows = read_rows("a;b\n1;2\n\n3;4\n", delimiter=";")
    assert [(r["a"], r["b"]) for r in rows] == [("1", "2"), ("3", "4")]


def test_bad_rows_and_headers():
    with pytest.raises(RowError):
        read_rows("a,b\n1,2,3\n")
    with pytest.raises(ValueError):
        read_rows("a,A\n1,2\n")
    assert read_rows("") == []
