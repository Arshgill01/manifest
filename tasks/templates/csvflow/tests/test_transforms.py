from csvflow.transforms import dedupe, derive, filter_rows, rename


def test_rename():
    assert rename([{"a": 1, "b": 2}], {"a": "x"}) == [{"x": 1, "b": 2}]


def test_derive_and_filter():
    rows = derive([{"q": 2, "p": 3.0}, {"q": 1, "p": 1.0}], "total", lambda r: r["q"] * r["p"])
    assert [r["total"] for r in rows] == [6.0, 1.0]
    assert filter_rows(rows, lambda r: r["total"] > 2) == [rows[0]]


def test_dedupe_keeps_first():
    rows = [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}, {"id": 1, "v": "c"}]
    assert dedupe(rows, ["id"]) == [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}]
