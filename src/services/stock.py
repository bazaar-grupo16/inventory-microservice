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
    RegisterStockDTO,
    ReleaseStockDTO,
    ReleaseBatchDTO,
    CommitOrderDTO,
    ReserveStockDTO,
    ReserveBatchItemDTO,
    StockQuantityRequestDTO,
    StockQuantityChangeDTO,
    StockNotificationMetadataDTO,
    UpdateStockDTO,
)
from src.exceptions.stock import (
    BatchStockIssue,
    InsufficientStock,
    StockNotFound,
)
from src.models.stock import Stock
from src.repositories.stock import StockRepository
from src.services.catalog import CatalogService
from src.services.notifications import NotificationsService


logger = logging.getLogger(__name__)


class StockService:
    """Pure business logic — no SQLAlchemy imports, no HTTP awareness."""

    def __init__(
        self,
        repository: StockRepository,
        catalog_service: CatalogService,
        notifications_service: NotificationsService,
    ) -> None:
        self.repository = repository
        self.catalog_service = catalog_service
        self.notifications_service = notifications_service

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
        self._notify_stock_threshold_crossing(change, dto.notification_metadata)
        return stock

    def reserve_stock(self, dto: ReserveStockDTO) -> Stock:
        """Atomically decrement stock; raise InsufficientStock if not possible."""
        change = self.repository.reserve(dto.product_id, dto.quantity, dto.order_id)
        if change is None:
            # Could be not found or insufficient — distinguish for the caller.
            stock = self.repository.find_by_id(dto.product_id)
            if stock is None:
                raise StockNotFound(dto.product_id)
            raise InsufficientStock(dto.product_id, stock.quantity)
        stock = self.repository.find_by_id(dto.product_id)
        assert stock is not None  # just committed
        if change.previous_quantity != change.new_quantity:
            self._notify_reserve_stock(change)
            self._notify_stock_threshold_crossing(change, dto.notification_metadata)
        return stock

    def release_stock(self, dto: ReleaseStockDTO) -> Stock:
        """Restore previously reserved stock (used on order cancellation)."""
        change = self.repository.release(dto.product_id, dto.order_id)
        if change is not None:
            self._notify_release_stock(change)
        stock = self.repository.find_by_id(dto.product_id)
        if stock is None:
            raise StockNotFound(dto.product_id)
        return stock

    def reserve_stocks(self, items: list[ReserveBatchItemDTO]) -> dict[UUID, int]:
        """Atomically reserve stock for multiple products in one transaction."""
        if not items:
            return {}
        order_id = items[0].order_id
        changes = self.repository.batch_reserve(order_id, items)
        metadata_by_product_id = {
            item.product_id: item.notification_metadata
            for item in items
            if item.notification_metadata is not None
        }
        for change in changes:
            if change.previous_quantity == change.new_quantity:
                continue
            self._notify_reserve_stock(change)
            self._notify_stock_threshold_crossing(
                change,
                metadata_by_product_id.get(change.product_id),
            )
        return {change.product_id: change.new_quantity for change in changes}

    def release_stocks(self, dto: ReleaseBatchDTO) -> dict[UUID, int]:
        """Restore reserved stock for multiple products in one transaction."""
        changes = self.repository.batch_release(dto.order_id)
        for change in changes:
            self._notify_release_stock(change)
        return {change.product_id: change.new_quantity for change in changes}

    def commit_stocks(self, dto: CommitOrderDTO) -> list[UUID]:
        """Commit all reservations for a given order_id."""
        return self.repository.batch_commit(dto.order_id)

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

    def _notify_stock_threshold_crossing(
        self,
        change: StockQuantityChangeDTO,
        metadata: StockNotificationMetadataDTO | None,
    ) -> None:
        if metadata is None:
            return

        threshold = self.notifications_service.settings.LOW_STOCK_THRESHOLD
        try:
            if change.previous_quantity > 0 and change.new_quantity == 0:
                self.notifications_service.notify_out_of_stock(
                    seller_id=metadata.seller_id,
                    product_id=change.product_id,
                    product_name=metadata.product_name,
                )
            elif (
                change.previous_quantity >= threshold
                and change.new_quantity < threshold
            ):
                self.notifications_service.notify_low_stock(
                    seller_id=metadata.seller_id,
                    product_id=change.product_id,
                    product_name=metadata.product_name,
                    current_stock=change.new_quantity,
                    threshold=threshold,
                )
        except Exception as exc:
            logger.warning(
                "NotificationsService raised unexpectedly for product %s: %s",
                change.product_id,
                exc,
            )

    def _collapse_requested_quantities(
        self, items: list[ReserveBatchItemDTO] | list[StockQuantityRequestDTO]
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
