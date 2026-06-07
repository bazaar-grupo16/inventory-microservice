"""
Background cleanup task for expired stock reservations.
"""

import asyncio
import logging
import random
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.utils import utc_now
from src.models.reservation import Reservation, ReservationStatus
from src.models.stock import Stock

logger = logging.getLogger(__name__)


def release_expired_reservations(db: Session) -> int:
    """
    Find expired reservations and release them, restoring stock.
    Returns the number of expired reservations released.

    Uses `with_for_update(skip_locked=True)` so that if concurrent cleanup
    tasks overlap, the second one will skip already-locked rows instead
    of blocking (preventing deadlocks and redundant processing).
    """
    try:
        # Fetch expired reservations. Use SKIP LOCKED to prevent blocking or
        # deadlocks if another cleanup task runs concurrently.
        stmt = (
            select(Reservation)
            .where(
                Reservation.expires_at.isnot(None),
                Reservation.expires_at < utc_now(),
                Reservation.status == ReservationStatus.PENDING.value
            )
            .with_for_update(skip_locked=True)
        )
        expired_reservations = db.scalars(stmt).all()
        if not expired_reservations:
            db.commit()
            return 0

        # Sort the reservations by product_id before locking stock rows
        # to ensure a consistent lock acquisition order and prevent deadlocks.
        sorted_reservations = sorted(expired_reservations, key=lambda r: r.product_id)
        
        released_count = 0
        for res in sorted_reservations:
            # Lock the stock row for the product to ensure atomic quantity update.
            stock = db.scalar(
                select(Stock)
                .where(Stock.product_id == res.product_id)
                .with_for_update()
            )
            if stock is not None:
                stock.quantity += res.quantity
                db.add(stock)
            else:
                logger.warning(
                    "Stock record not found for product_id %s of expired reservation (%s)",
                    res.product_id, res.order_id
                )
            
            db.delete(res)
            released_count += 1
            
        db.commit()
        return released_count
    except Exception:
        db.rollback()
        raise


async def start_cleanup_loop(interval_seconds: int, session_factory) -> None:
    """
    Periodically runs the reservation cleanup task.
    """
    logger.info("Starting background cleanup loop with interval %d seconds", interval_seconds)
    try:
        while True:
            time_to_sleep = interval_seconds + interval_seconds * random.uniform(0, 0.25)
            await asyncio.sleep(time_to_sleep)
            try:
                with session_factory() as db:
                    released = release_expired_reservations(db)
                    if released > 0:
                        logger.info(
                            "Released %d expired reservations",
                            released,
                            extra={"released_count": released}
                        )
            except Exception as exc:
                logger.exception("Error in cleanup loop iteration: %s", exc)
    except asyncio.CancelledError:
        logger.info("Cleanup loop cancelled cleanly.")
        raise
