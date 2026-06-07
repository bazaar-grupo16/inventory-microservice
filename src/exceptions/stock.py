"""
Domain exceptions for stock operations.
"""

from __future__ import annotations

from uuid import UUID


class BatchStockIssue:
    def __init__(self, product_id: UUID, requested: int, available: int) -> None:
        self.product_id = product_id
        self.requested = requested
        self.available = available


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


class BatchInsufficientStock(Exception):
    """Raised when one or more products in a batch reservation lack stock."""

    def __init__(self, issues: list[BatchStockIssue]) -> None:
        self.issues = issues
        summary = "; ".join(
            f"{issue.product_id} (requested {issue.requested}, available {issue.available})"
            for issue in issues
        )
        super().__init__(f"Products out of stock: {summary}")


class BatchStockNotFound(Exception):
    """Raised when one or more products in a batch release do not exist."""

    def __init__(self, product_ids: list[UUID]) -> None:
        self.product_ids = product_ids
        summary = ", ".join(str(product_id) for product_id in product_ids)
        super().__init__(f"Stock entries not found for products: {summary}")


class ReservationNotFound(Exception):
    """Raised when attempting to commit a reservation that does not exist."""

    def __init__(self, order_id: UUID) -> None:
        self.order_id = order_id
        super().__init__(f"No active reservations found for order {order_id}")
