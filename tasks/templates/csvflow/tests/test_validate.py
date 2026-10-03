from datetime import date

import pytest

from csvflow.reader import read_rows
from csvflow.schema import Column, Schema
from csvflow.validate import SchemaError, validate

from .helpers import SALES, SCHEMA


def test_good_rows_are_typed():
    good, _ = validate(read_rows(SALES), SCHEMA)
    assert len(good) == 4
    assert good[0] == {"order_id": "A1", "region": "north", "amount": 120.5,
                       "shipped_on": date(2026, 1, 3), "express": True}


def test_issues_point_at_file_lines():
    _, issues = validate(read_rows(SALES), SCHEMA)
    assert [(i.line, i.column) for i in issues] == [(5, "amount"), (6, "amount")]


def test_missing_required_column():
    with pytest.raises(SchemaError):
        validate(read_rows("order_id\nA1\n"), SCHEMA)


def test_optional_column_may_be_absent():
    schema = Schema((Column("a", "int"), Column("note", required=False, default="-")))
    good, issues = validate(read_rows("a\n1\n"), schema)
    assert good == [{"a": 1, "note": "-"}] and issues == []
