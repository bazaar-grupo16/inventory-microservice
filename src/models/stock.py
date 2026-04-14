"""
Stock ORM model for the inventory microservice.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from src.core.database import Base
from src.core.utils import utc_now


class Stock(Base):
    """Persisted stock level for a product."""

    __tablename__ = "stocks"

    __table_args__ = (CheckConstraint("quantity >= 0", name="quantity_non_negative"),)

    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
