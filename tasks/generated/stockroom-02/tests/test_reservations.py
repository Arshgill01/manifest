from datetime import timedelta

import pytest

from stockroom.inventory import InsufficientStock
from stockroom.reservations import ReservationExpired, UnknownReservation

from .helpers import T0, make_book


def test_reserve_reduces_available():
    book = make_book()
    book.reserve("BOLT-M6", 120, T0)
    assert book.reserved("BOLT-M6") == 120
    assert book.available("BOLT-M6") == 380


def test_cannot_reserve_more_than_available():
    book = make_book()
    book.reserve("NUT-M6", 80, T0)
    with pytest.raises(InsufficientStock):
        book.reserve("NUT-M6", 21, T0)


def test_reservation_expires_at_ttl():
    book = make_book()
    r = book.reserve("BOLT-M6", 120, T0)
    assert book.expire(T0 + timedelta(minutes=15)) == [r.id]
    assert book.available("BOLT-M6") == 500


def test_reservation_held_before_ttl():
    book = make_book()
    book.reserve("BOLT-M6", 120, T0)
    assert book.expire(T0 + timedelta(minutes=14)) == []
    assert book.available("BOLT-M6") == 380


def test_commit_ships_across_locations():
    book = make_book()
    r = book.reserve("BOLT-M6", 350, T0)
    assert book.commit(r.id, T0 + timedelta(minutes=1)) == [("MAIN", 300), ("STORE", 50)]
    assert book.inventory.on_hand("BOLT-M6") == 150
    assert book.reserved("BOLT-M6") == 0


def test_commit_after_expiry_fails_and_keeps_stock():
    book = make_book()
    r = book.reserve("NUT-M6", 10, T0)
    with pytest.raises(ReservationExpired):
        book.commit(r.id, T0 + timedelta(minutes=20))
    assert book.inventory.on_hand("NUT-M6") == 100


def test_ids_and_release():
    book = make_book()
    assert book.reserve("NUT-M6", 1, T0).id == "R0001"
    assert book.reserve("NUT-M6", 1, T0).id == "R0002"
    book.release("R0001")
    with pytest.raises(UnknownReservation):
        book.release("R0001")
