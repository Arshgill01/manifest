import pytest

from stockroom.catalog import Catalog, Product, UnknownSku

from .helpers import make_catalog


def test_unknown_sku():
    with pytest.raises(UnknownSku):
        make_catalog().get("NOPE")


def test_duplicate_sku_rejected():
    cat = make_catalog()
    with pytest.raises(ValueError):
        cat.add(Product("WASHER", "again"))


def test_pack_size_must_be_positive():
    with pytest.raises(ValueError):
        Catalog([Product("X", "x", pack_size=0)])


def test_skus_sorted():
    cat = make_catalog()
    assert cat.skus() == ["BOLT-M6", "NUT-M6", "WASHER"]
    assert len(cat) == 3
