"""
Domain exceptions for stock operations.
"""

from __future__ import annotations

from uuid import UUID


class StockNotFound(Exception):
    """Raised when stock for a product does not exist."""

    def __init__(self, product_id: UUID) -> None:
        self.product_id = product_id
        super().__init__(f"Stock for product {product_id} not found")


class InsufficientStock(Exception):
    """Raised when a reservation would push stock below zero."""

    def __init__(self, product_id: UUID, available: int) -> None:
        self.product_id = product_id
        self.available = available
        super().__init__(f"Product {product_id} has only {available} units available.")
