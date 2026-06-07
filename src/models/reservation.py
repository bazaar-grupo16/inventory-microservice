"""
Reservation ORM model for the inventory microservice.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid
from enum import StrEnum

from src.core.database import Base


class ReservationStatus(StrEnum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"

class Reservation(Base):
    """Persisted reservation for a product order."""

    __tablename__ = "reservations"

    order_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stocks.product_id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[ReservationStatus] = mapped_column(
        String(30),
        nullable=False,
        default=ReservationStatus.PENDING.value,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
