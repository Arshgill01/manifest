"""Product catalog."""

from __future__ import annotations

from dataclasses import dataclass


class UnknownSku(KeyError):
    pass


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    pack_size: int = 1
    reorder_point: int = 0
    reorder_qty: int = 0
    lead_time_days: int = 7


class Catalog:
    def __init__(self, products=()):
        self._products: dict[str, Product] = {}
        for product in products:
            self.add(product)

    def add(self, product: Product) -> None:
        if product.pack_size < 1:
            raise ValueError(f"{product.sku}: pack size must be at least 1")
        if product.sku in self._products:
            raise ValueError(f"duplicate sku {product.sku}")
        self._products[product.sku] = product

    def get(self, sku: str) -> Product:
        try:
            return self._products[sku]
        except KeyError:
            raise UnknownSku(sku) from None

    def skus(self) -> list[str]:
        return sorted(self._products)

    def __len__(self) -> int:
        return len(self._products)
