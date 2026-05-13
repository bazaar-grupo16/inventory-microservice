"""
Business logic for stock operations.

The service layer has no SQLAlchemy imports and no knowledge of HTTP.
It raises domain exceptions that are translated to HTTP responses in
the exception handlers registered in main.py.
"""

from __future__ import annotations

import logging
from uuid import UUID

from src.dtos import (
    BatchStocksDTO,
    BatchStockQuantityRequestDTO,
    RegisterStockDTO,
    ReleaseStockDTO,
    ReserveStockDTO,
    StockQuantityRequestDTO,
    StockQuantityChangeDTO,
    UpdateStockDTO,
)
from src.exceptions.stock import (
    BatchInsufficientStock,
    BatchStockIssue,
    BatchStockNotFound,
    InsufficientStock,
    StockNotFound,
)
from src.models.stock import Stock
from src.repositories.stock import StockRepository
from src.services.catalog import CatalogService


logger = logging.getLogger(__name__)


class StockService:
    """Pure business logic — no SQLAlchemy imports, no HTTP awareness."""

    def __init__(
        self, repository: StockRepository, catalog_service: CatalogService
    ) -> None:
        self.repository = repository
        self.catalog_service = catalog_service

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
        previous_quantity = stock.quantity
        stock.quantity = dto.quantity
        change = self.repository.save_with_previous_quantity(stock, previous_quantity)
        self._notify_update_stock(change)
        return stock

    def reserve_stock(self, dto: ReserveStockDTO) -> Stock:
        """Atomically decrement stock; raise InsufficientStock if not possible."""
        change = self.repository.reserve(dto.product_id, dto.quantity)
        if change is None:
            # Could be not found or insufficient — distinguish for the caller.
            stock = self.repository.find_by_id(dto.product_id)
            if stock is None:
                raise StockNotFound(dto.product_id)
            raise InsufficientStock(dto.product_id, stock.quantity)
        stock = self.repository.find_by_id(dto.product_id)
        assert stock is not None  # just committed
        self._notify_reserve_stock(change)
        return stock

    def release_stock(self, dto: ReleaseStockDTO) -> Stock:
        """Restore previously reserved stock (used on order cancellation)."""
        stock = self.repository.find_by_id(dto.product_id)
        if stock is None:
            raise StockNotFound(dto.product_id)
        previous_quantity = stock.quantity
        stock.quantity += dto.quantity
        change = self.repository.save_with_previous_quantity(stock, previous_quantity)
        self._notify_release_stock(change)
        return stock

    def reserve_stocks(self, dto: BatchStockQuantityRequestDTO) -> dict[UUID, int]:
        """Atomically reserve stock for multiple products in one transaction."""
        requested_quantities = self._collapse_requested_quantities(dto.items)
        stocks = self.repository.find_by_ids_for_update(list(requested_quantities))
        issues = self._collect_reservation_issues(requested_quantities, stocks)
        if issues:
            raise BatchInsufficientStock(issues)

        stock_changes: list[tuple[Stock, int]] = []
        for product_id, quantity in requested_quantities.items():
            stock = stocks[product_id]
            previous_quantity = stock.quantity
            stock.quantity -= quantity
            stock_changes.append((stock, previous_quantity))

        changes = self.repository.save_many_with_previous_quantities(stock_changes)
        for change in changes:
            self._notify_reserve_stock(change)
        return {change.product_id: change.new_quantity for change in changes}

    def release_stocks(self, dto: BatchStockQuantityRequestDTO) -> dict[UUID, int]:
        """Restore reserved stock for multiple products in one transaction."""
        requested_quantities = self._collapse_requested_quantities(dto.items)
        stocks = self.repository.find_by_ids_for_update(list(requested_quantities))
        missing_product_ids = [
            product_id for product_id in requested_quantities if product_id not in stocks
        ]
        if missing_product_ids:
            raise BatchStockNotFound(missing_product_ids)

        stock_changes: list[tuple[Stock, int]] = []
        for product_id, quantity in requested_quantities.items():
            stock = stocks[product_id]
            previous_quantity = stock.quantity
            stock.quantity += quantity
            stock_changes.append((stock, previous_quantity))

        changes = self.repository.save_many_with_previous_quantities(stock_changes)
        for change in changes:
            self._notify_release_stock(change)
        return {change.product_id: change.new_quantity for change in changes}

    def _notify_reserve_stock(self, change: StockQuantityChangeDTO) -> None:
        if change.new_quantity == 0:
            self._notify_catalog_stock_status(change.product_id, has_stock=False)

    def _notify_release_stock(self, change: StockQuantityChangeDTO) -> None:
        if change.previous_quantity == 0 and change.new_quantity > 0:
            self._notify_catalog_stock_status(change.product_id, has_stock=True)

    def _notify_update_stock(self, change: StockQuantityChangeDTO) -> None:
        if change.previous_quantity > 0 and change.new_quantity == 0:
            self._notify_catalog_stock_status(change.product_id, has_stock=False)
        elif change.previous_quantity == 0 and change.new_quantity > 0:
            self._notify_catalog_stock_status(change.product_id, has_stock=True)

    def _notify_catalog_stock_status(self, product_id: UUID, has_stock: bool) -> None:
        try:
            self.catalog_service.notify_stock_status(product_id, has_stock=has_stock)
        except Exception as exc:
            logger.warning(
                "CatalogService raised unexpectedly for product %s: %s",
                product_id,
                exc,
            )

    def _collapse_requested_quantities(
        self, items: list[StockQuantityRequestDTO]
    ) -> dict[UUID, int]:
        collapsed: dict[UUID, int] = {}
        for item in items:
            collapsed[item.product_id] = collapsed.get(item.product_id, 0) + item.quantity
        return collapsed

    def _collect_reservation_issues(
        self,
        requested_quantities: dict[UUID, int],
        stocks: dict[UUID, Stock],
    ) -> list[BatchStockIssue]:
        issues: list[BatchStockIssue] = []
        for product_id, requested_quantity in requested_quantities.items():
            stock = stocks.get(product_id)
            available_quantity = stock.quantity if stock is not None else 0
            if stock is None or available_quantity < requested_quantity:
                issues.append(
                    BatchStockIssue(
                        product_id=product_id,
                        requested=requested_quantity,
                        available=available_quantity,
                    )
                )
        return issues
