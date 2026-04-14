"""
Database queries for stock entities.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from src.models.stock import Stock


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

    def delete(self, stock: Stock) -> None:
        """Delete a stock entry from the database."""
        self.db.delete(stock)
        self.db.commit()

    def find_by_ids(self, product_ids: list[UUID]) -> dict[UUID, int]:
        """Return a mapping of product_id → quantity for the given IDs."""
        query = select(Stock).where(Stock.product_id.in_(product_ids))
        rows = self.db.scalars(query).all()
        return {row.product_id: row.quantity for row in rows}

    def reserve(self, product_id: UUID, quantity: int) -> bool:
        """Atomically decrement stock by quantity.

        Uses a single UPDATE … WHERE quantity >= :qty to prevent concurrent
        over-reservations.  Returns True if a row was updated, False if the
        stock was insufficient (or the entry does not exist).
        """
        stmt = (
            update(Stock)
            .where(Stock.product_id == product_id, Stock.quantity >= quantity)
            .values(
                quantity=Stock.quantity - quantity,
                updated_at=text("NOW()"),
            )
            .execution_options(synchronize_session="fetch")
        )
        result = self.db.execute(stmt)
        self.db.commit()
        return result.rowcount > 0
