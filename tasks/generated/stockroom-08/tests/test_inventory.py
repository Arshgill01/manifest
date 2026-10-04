import pytest

from stockroom.catalog import UnknownSku
from stockroom.inventory import InsufficientStock, Inventory

from .helpers import make_catalog


def make_inventory():
    return Inventory(make_catalog())


def test_receive_and_ship_at_location():
    inv = make_inventory()
    inv.receive("BOLT-M6", 300, "MAIN")
    inv.ship("BOLT-M6", 120, "MAIN")
    assert inv.on_hand("BOLT-M6", "MAIN") == 180


def test_cannot_ship_more_than_on_hand():
    inv = make_inventory()
    inv.receive("NUT-M6", 10, "MAIN")
    with pytest.raises(InsufficientStock):
        inv.ship("NUT-M6", 11, "MAIN")
    assert inv.on_hand("NUT-M6", "MAIN") == 10


def test_quantities_are_validated():
    inv = make_inventory()
    with pytest.raises(UnknownSku):
        inv.receive("NOPE", 1)
    for bad in (0, -5, 2.5, True):
        with pytest.raises(ValueError):
            inv.receive("WASHER", bad)


def test_transfer_between_locations():
    inv = make_inventory()
    inv.receive("BOLT-M6", 100, "MAIN")
    inv.transfer("BOLT-M6", 40, "MAIN", "STORE")
    assert inv.on_hand("BOLT-M6", "MAIN") == 60
    assert inv.on_hand("BOLT-M6", "STORE") == 40
    assert inv.locations("BOLT-M6") == ["MAIN", "STORE"]


def test_pick_draws_locations_in_order():
    inv = make_inventory()
    inv.receive("WASHER", 30, "A1")
    inv.receive("WASHER", 50, "B2")
    assert inv.pick("WASHER", 40) == [("A1", 30), ("B2", 10)]
    assert inv.on_hand("WASHER", "B2") == 40
    assert inv.locations("WASHER") == ["B2"]


def test_pick_is_all_or_nothing():
    inv = make_inventory()
    inv.receive("WASHER", 5, "A1")
    with pytest.raises(InsufficientStock):
        inv.pick("WASHER", 6)
    assert inv.on_hand("WASHER", "A1") == 5
