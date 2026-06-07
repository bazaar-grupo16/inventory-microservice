"""
Database queries for stock entities.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.utils import utc_now
from src.dtos import StockQuantityChangeDTO, ReserveBatchItemDTO
from src.models.stock import Stock
from src.models.reservation import Reservation
from src.exceptions.stock import (
    StockNotFound,
    ReservationNotFound,
)

settings = get_settings()


class StockRepository:
    """Repository for stock database operations.

    This is the only layer that imports and uses SQLAlchemy Session directly.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, stock: Stock) -> Stock:
        """Persist a new stock entry and return the refreshed instance."""
        self.db.add(stock)
        self.db.commit()
        self.db.refresh(stock)
        return stock

    def find_by_id(self, product_id: UUID) -> Stock | None:
        """Fetch a single stock entry by product_id."""
        query = select(Stock).where(Stock.product_id == product_id)
        return self.db.scalar(query)

    def save(self, stock: Stock) -> Stock:
        """Persist changes to an existing stock entry and return the refreshed instance."""
        self.db.add(stock)
        self.db.commit()
        self.db.refresh(stock)
        return stock

    def save_with_previous_quantity(
        self, stock: Stock, previous_quantity: int
    ) -> StockQuantityChangeDTO:
        """Persist a stock change and return both the old and new quantities."""
        self.db.add(stock)
        self.db.commit()
        self.db.refresh(stock)
        return StockQuantityChangeDTO(
            product_id=stock.product_id,
            previous_quantity=previous_quantity,
            new_quantity=stock.quantity,
        )

    def save_many_with_previous_quantities(
        self, stock_changes: list[tuple[Stock, int]]
    ) -> list[StockQuantityChangeDTO]:
        """Persist multiple stock changes in a single transaction."""
        for stock, _previous_quantity in stock_changes:
            self.db.add(stock)
        self.db.commit()
        for stock, _previous_quantity in stock_changes:
            self.db.refresh(stock)
        return [
            StockQuantityChangeDTO(
                product_id=stock.product_id,
                previous_quantity=previous_quantity,
                new_quantity=stock.quantity,
            )
            for stock, previous_quantity in stock_changes
        ]

    def delete(self, stock: Stock) -> None:
        """Delete a stock entry from the database."""
        self.db.delete(stock)
        self.db.commit()

    def find_by_ids(self, product_ids: list[UUID]) -> dict[UUID, int]:
        """Return a mapping of product_id → quantity for the given IDs."""
        query = select(Stock).where(Stock.product_id.in_(product_ids))
        rows = self.db.scalars(query).all()
        return {row.product_id: row.quantity for row in rows}

    def find_by_ids_for_update(self, product_ids: list[UUID]) -> dict[UUID, Stock]:
        """Fetch stock rows and lock them for update inside the current transaction."""
        query = select(Stock).where(Stock.product_id.in_(product_ids)).with_for_update()
        rows = self.db.scalars(query).all()
        return {row.product_id: row for row in rows}

    def reserve(
        self, product_id: UUID, quantity: int, order_id: UUID | None = None
    ) -> StockQuantityChangeDTO | None:
        """Atomically decrement stock by quantity."""
        try:
            # Lock the stock row to serialize concurrent reservations for this product
            stock = self.db.scalar(
                select(Stock)
                .where(Stock.product_id == product_id)
                .with_for_update()
            )
            if stock is None:
                self.db.commit()
                return None

            # If order_id is provided, check for idempotency
            if order_id is not None:
                existing = self.db.scalar(
                    select(Reservation)
                    .where(
                        Reservation.order_id == order_id,
                        Reservation.product_id == product_id,
                    )
                )
                if existing is not None:
                    # Idempotent match: already reserved!
                    self.db.commit()
                    return StockQuantityChangeDTO(
                        product_id=product_id,
                        previous_quantity=stock.quantity,
                        new_quantity=stock.quantity,
                    )

            if stock.quantity < quantity:
                self.db.commit()
                return None

            previous_quantity = stock.quantity
            stock.quantity -= quantity
            self.db.add(stock)

            if order_id is not None:
                reservation = Reservation(
                    order_id=order_id,
                    product_id=product_id,
                    quantity=quantity,
                    expires_at=None,
                )
                self.db.add(reservation)

            self.db.commit()

            return StockQuantityChangeDTO(
                product_id=product_id,
                previous_quantity=previous_quantity,
                new_quantity=stock.quantity,
            )
        except Exception:
            self.db.rollback()
            raise

    def release(
        self, product_id: UUID, order_id: UUID
    ) -> StockQuantityChangeDTO | None:
        """Release the reservation for (order_id, product_id) and restore stock."""
        try:
            # Lock the reservation row to check if it exists
            res = self.db.scalar(
                select(Reservation)
                .where(
                    Reservation.order_id == order_id,
                    Reservation.product_id == product_id,
                )
                .with_for_update()
            )
            if res is None:
                # Idempotent: already released or never existed
                self.db.commit()
                return None

            # Lock the stock row
            stock = self.db.scalar(
                select(Stock)
                .where(Stock.product_id == product_id)
                .with_for_update()
            )
            if stock is None:
                raise StockNotFound(product_id)

            previous_quantity = stock.quantity
            stock.quantity += res.quantity
            self.db.add(stock)

            # Delete the reservation
            self.db.delete(res)

            self.db.commit()

            return StockQuantityChangeDTO(
                product_id=product_id,
                previous_quantity=previous_quantity,
                new_quantity=stock.quantity,
            )
        except Exception:
            self.db.rollback()
            raise

    def batch_reserve(
        self, order_id: UUID, items: list[ReserveBatchItemDTO]
    ) -> list[StockQuantityChangeDTO]:
        """Atomically reserve stock for multiple products in one transaction."""
        collapsed: dict[UUID, ReserveBatchItemDTO] = {}
        for item in items:
            if item.product_id in collapsed:
                collapsed[item.product_id].quantity += item.quantity
            else:
                collapsed[item.product_id] = ReserveBatchItemDTO(
                    product_id=item.product_id,
                    quantity=item.quantity,
                    order_id=item.order_id,
                    notification_metadata=item.notification_metadata,
                )

        sorted_items = sorted(collapsed.values(), key=lambda x: x.product_id)
        
        try:
            # First, lock all products in sorted order to serialize concurrent requests
            stocks_by_id = {}
            for item in sorted_items:
                stock = self.db.scalar(
                    select(Stock)
                    .where(Stock.product_id == item.product_id)
                    .with_for_update()
                )
                if stock is not None:
                    stocks_by_id[item.product_id] = stock

            # Lock the existing reservations for this order to check for idempotency
            existing = self.db.scalars(
                select(Reservation)
                .where(Reservation.order_id == order_id)
            ).all()
            if existing:
                self.db.commit()
                product_ids = [res.product_id for res in existing]
                stocks = self.db.scalars(
                    select(Stock).where(Stock.product_id.in_(product_ids))
                ).all()
                return [
                    StockQuantityChangeDTO(
                        product_id=s.product_id,
                        previous_quantity=s.quantity,
                        new_quantity=s.quantity,
                    )
                    for s in stocks
                ]

            from src.exceptions.stock import BatchStockIssue, BatchInsufficientStock
            issues: list[BatchStockIssue] = []
            
            # Check all products and collect issues
            for item in sorted_items:
                stock = stocks_by_id.get(item.product_id)
                if stock is None:
                    issues.append(BatchStockIssue(item.product_id, item.quantity, 0))
                elif stock.quantity < item.quantity:
                    issues.append(BatchStockIssue(item.product_id, item.quantity, stock.quantity))

            if issues:
                raise BatchInsufficientStock(issues)

            # If no issues, perform the decrements and inserts
            changes: list[StockQuantityChangeDTO] = []
            expires_at = utc_now() + timedelta(minutes=settings.RESERVATION_TTL_MINUTES)
            for item in sorted_items:
                stock = stocks_by_id[item.product_id]
                previous_quantity = stock.quantity
                stock.quantity -= item.quantity
                self.db.add(stock)

                reservation = Reservation(
                    order_id=order_id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    expires_at=expires_at,
                )
                self.db.add(reservation)
                
                changes.append(
                    StockQuantityChangeDTO(
                        product_id=item.product_id,
                        previous_quantity=previous_quantity,
                        new_quantity=stock.quantity,
                    )
                )
            
            self.db.commit()
            return changes
        except Exception:
            self.db.rollback()
            raise

    def batch_release(self, order_id: UUID) -> list[StockQuantityChangeDTO]:
        """Release all reservations for a given order_id."""
        try:
            # First, fetch all reservations for this order, locked for update
            reservations = self.db.scalars(
                select(Reservation)
                .where(Reservation.order_id == order_id)
                .with_for_update()
            ).all()
            
            if not reservations:
                self.db.commit()
                return []
            
            changes: list[StockQuantityChangeDTO] = []
            
            # Sort reservations by product_id to prevent deadlocks
            sorted_reservations = sorted(reservations, key=lambda r: r.product_id)
            
            for res in sorted_reservations:
                stock = self.db.scalar(
                    select(Stock)
                    .where(Stock.product_id == res.product_id)
                    .with_for_update()
                )
                if stock is None:
                    raise StockNotFound(res.product_id)
                
                previous_quantity = stock.quantity
                stock.quantity += res.quantity
                self.db.add(stock)
                
                self.db.delete(res)
                
                changes.append(
                    StockQuantityChangeDTO(
                        product_id=res.product_id,
                        previous_quantity=previous_quantity,
                        new_quantity=stock.quantity,
                    )
                )
            
            self.db.commit()
            return changes
        except Exception:
            self.db.rollback()
            raise

    def batch_commit(self, order_id: UUID) -> list[UUID]:
        """Commit all reservations for a given order_id by deleting reservation rows."""
        try:
            reservations = self.db.scalars(
                select(Reservation)
                .where(Reservation.order_id == order_id)
                .with_for_update()
            ).all()
            
            if not reservations:
                raise ReservationNotFound(order_id)
            
            product_ids = [res.product_id for res in reservations]
            
            for res in reservations:
                self.db.delete(res)
                
            self.db.commit()
            return product_ids
        except Exception:
            self.db.rollback()
            raise
