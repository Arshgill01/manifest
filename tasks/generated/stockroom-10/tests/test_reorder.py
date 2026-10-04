from datetime import date

from stockroom.reorder import expected_arrival, needs_reorder, position, round_to_pack, suggested_order

from .helpers import make_book, make_catalog


def test_reorder_triggers_at_exact_point():
    bolt = make_catalog().get("BOLT-M6")
    assert needs_reorder(bolt, 500)
    assert not needs_reorder(bolt, 501)


def test_order_at_exact_point():
    bolt = make_catalog().get("BOLT-M6")
    assert suggested_order(bolt, 500) == 1000


def test_order_rounds_up_to_whole_packs():
    nut = make_catalog().get("NUT-M6")
    assert suggested_order(nut, 130) == 500


def test_no_order_above_reorder_point():
    nut = make_catalog().get("NUT-M6")
    assert suggested_order(nut, 250) == 0


def test_round_to_pack():
    assert [round_to_pack(q, 100) for q in (1, 100, 101)] == [100, 100, 200]
    assert round_to_pack(7, 1) == 7


def test_arrival_and_position():
    cat = make_catalog()
    assert expected_arrival(cat.get("BOLT-M6"), date(2026, 3, 2)) == date(2026, 3, 7)
    assert position(cat.get("BOLT-M6"), make_book(), incoming=300) == 800
