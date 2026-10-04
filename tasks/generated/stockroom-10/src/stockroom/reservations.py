"""Time-limited stock reservations (e.g. items sitting in a checkout cart)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .inventory import InsufficientStock, Inventory


class UnknownReservation(KeyError):
    pass


class ReservationExpired(ValueError):
    pass


@dataclass
class Reservation:
    id: str
    sku: str
    qty: int
    expires_at: datetime


class ReservationBook:
    def __init__(self, inventory: Inventory, ttl: timedelta = timedelta(minutes=15)):
        self.inventory = inventory
        self.ttl = ttl
        self._active: dict[str, Reservation] = {}
        self._seq = 0

    def reserved(self, sku: str) -> int:
        return sum(r.qty for r in self._active.values() if r.sku == sku)

    def available(self, sku: str) -> int:
        return self.inventory.on_hand(sku) - self.reserved(sku)

    def expire(self, now: datetime) -> list[str]:
        """Drop reservations whose time is up; returns their ids."""
        expired = [rid for rid, r in self._active.items() if r.expires_at < now]
        for rid in expired:
            del self._active[rid]
        return expired

    def reserve(self, sku: str, qty: int, now: datetime) -> Reservation:
        self.expire(now)
        if qty <= 0:
            raise ValueError("reservation quantity must be positive")
        if qty > self.available(sku):
            raise InsufficientStock(f"{sku}: cannot reserve {qty}, only {self.available(sku)} available")
        self._seq += 1
        reservation = Reservation(f"R{self._seq:04d}", sku, qty, now + self.ttl)
        self._active[reservation.id] = reservation
        return reservation

    def release(self, rid: str) -> Reservation:
        try:
            return self._active.pop(rid)
        except KeyError:
            raise UnknownReservation(rid) from None

    def commit(self, rid: str, now: datetime) -> list[tuple[str, int]]:
        """Turn a reservation into a shipment."""
        if rid not in self._active:
            raise UnknownReservation(rid)
        reservation = self._active[rid]
        if reservation.expires_at <= now:
            del self._active[rid]
            raise ReservationExpired(rid)
        del self._active[rid]
        return self.inventory.pick(reservation.sku, reservation.qty)
