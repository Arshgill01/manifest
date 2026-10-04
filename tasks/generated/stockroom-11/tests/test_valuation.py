from decimal import Decimal

import pytest

from stockroom.inventory import InsufficientStock
from stockroom.valuation import FifoLedger


def test_consume_uses_oldest_cost_first():
    fifo = FifoLedger()
    fifo.receive("BOLT-M6", 100, "0.10")
    fifo.receive("BOLT-M6", 100, "0.12")
    assert fifo.consume("BOLT-M6", 150) == Decimal("16.00")
    assert fifo.quantity("BOLT-M6") == 50
    assert fifo.value("BOLT-M6") == Decimal("6.00")


def test_consecutive_consumes_walk_the_layers():
    fifo = FifoLedger()
    for cost in ("2.00", "3.00", "4.00"):
        fifo.receive("NUT-M6", 50, cost)
    assert fifo.consume("NUT-M6", 60) == Decimal("130.00")
    assert fifo.consume("NUT-M6", 60) == Decimal("200.00")
    assert fifo.value("NUT-M6") == Decimal("120.00")


def test_consume_whole_layer():
    fifo = FifoLedger()
    fifo.receive("WASHER", 10, "1.00")
    assert fifo.consume("WASHER", 10) == Decimal("10.00")
    assert fifo.quantity("WASHER") == 0
    assert fifo.average_cost("WASHER") == Decimal("0.00")


def test_average_cost():
    fifo = FifoLedger()
    fifo.receive("BOLT-M6", 100, "0.10")
    fifo.receive("BOLT-M6", 300, "0.14")
    assert fifo.average_cost("BOLT-M6") == Decimal("0.13")


def test_cannot_consume_more_than_held():
    fifo = FifoLedger()
    fifo.receive("WASHER", 1, "1.00")
    with pytest.raises(InsufficientStock):
        fifo.consume("WASHER", 2)
    assert fifo.value("NOPE") == Decimal("0.00")
