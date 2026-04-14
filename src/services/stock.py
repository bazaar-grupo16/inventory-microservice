"""
Business logic for stock operations.

The service layer has no SQLAlchemy imports and no knowledge of HTTP.
It raises domain exceptions that are translated to HTTP responses in
the exception handlers registered in main.py.
"""

from __future__ import annotations

from uuid import UUID

from src.dtos import (
    BatchStocksDTO,
    RegisterStockDTO,
    ReleaseStockDTO,
    ReserveStockDTO,
    UpdateStockDTO,
)
from src.exceptions.stock import InsufficientStock, StockNotFound
from src.models.stock import Stock
from src.repositories.stock import StockRepository


class StockService:
    """Pure business logic — no SQLAlchemy imports, no HTTP awareness."""

    def __init__(self, repository: StockRepository) -> None:
        self.repository = repository

    def register_stock(self, dto: RegisterStockDTO) -> Stock:
        """Create the initial stock entry for a newly created product."""
        stock = Stock(product_id=dto.product_id, quantity=dto.quantity)
        return self.repository.create(stock)

    def delete_stock(self, product_id: UUID) -> None:
        """Remove the stock entry when a product is deleted."""
        stock = self.repository.find_by_id(product_id)
        if stock is None:
            raise StockNotFound(product_id)
        self.repository.delete(stock)

    def get_stock(self, product_id: UUID) -> Stock:
        """Return the current stock entry for a single product."""
        stock = self.repository.find_by_id(product_id)
        if stock is None:
            raise StockNotFound(product_id)
        return stock

    def get_stocks(self, dto: BatchStocksDTO) -> dict[UUID, int]:
        """Return stock levels for multiple products in a single query."""
        return self.repository.find_by_ids(dto.product_ids)

    def update_stock(self, dto: UpdateStockDTO) -> Stock:
        """Fully replace the stock level for a product (manual adjustment)."""
        stock = self.repository.find_by_id(dto.product_id)
        if stock is None:
            raise StockNotFound(dto.product_id)
        stock.quantity = dto.quantity
        return self.repository.save(stock)

    def reserve_stock(self, dto: ReserveStockDTO) -> Stock:
        """Atomically decrement stock; raise InsufficientStock if not possible."""
        succeeded = self.repository.reserve(dto.product_id, dto.quantity)
        if not succeeded:
            # Could be not found or insufficient — distinguish for the caller.
            stock = self.repository.find_by_id(dto.product_id)
            if stock is None:
                raise StockNotFound(dto.product_id)
            raise InsufficientStock(dto.product_id, stock.quantity)
        stock = self.repository.find_by_id(dto.product_id)
        assert stock is not None  # just committed
        return stock

    def release_stock(self, dto: ReleaseStockDTO) -> Stock:
        """Restore previously reserved stock (used on order cancellation)."""
        stock = self.repository.find_by_id(dto.product_id)
        if stock is None:
            raise StockNotFound(dto.product_id)
        stock.quantity += dto.quantity
        return self.repository.save(stock)
