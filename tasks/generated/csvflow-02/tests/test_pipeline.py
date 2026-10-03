from csvflow.pipeline import run
from csvflow.schema import Column, Schema

from .helpers import SALES, SCHEMA


def test_full_pipeline():
    report = run(SALES, SCHEMA, dedupe_on=["order_id"], summarize_by="region", summarize_field="amount")
    assert [r["order_id"] for r in report.rows] == ["A1", "A2", "A3"]
    assert [i.line for i in report.issues] == [5, 6]
    assert report.summary["north"] == {"count": 2, "sum": 220.0, "mean": 110.0, "median": 110.0,
                                       "min": 99.5, "max": 120.5}
    assert report.summary["south"]["count"] == 1


def test_where_and_derived():
    report = run(SALES, SCHEMA, derived={"big": lambda r: r["amount"] > 100}, where=lambda r: r["express"])
    assert [(r["order_id"], r["big"]) for r in report.rows] == [("A1", True)]


def test_renames_before_validation():
    schema = Schema((Column("id"), Column("area")))
    report = run("Order ID,Region\nA1,north\n", schema, renames={"order_id": "id", "region": "area"})
    assert report.rows == [{"id": "A1", "area": "north"}]
