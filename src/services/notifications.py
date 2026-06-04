"""Best-effort client for stock notifications."""

from __future__ import annotations

import logging
from uuid import UUID

import httpx

from src.core.config import get_settings
from src.core.observability import build_observability_headers

logger = logging.getLogger(__name__)


class NotificationsService:
    """Best-effort client for inventory -> notifications events."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def notify_low_stock(
        self,
        *,
        seller_id: str,
        product_id: UUID,
        product_name: str,
        current_stock: int,
        threshold: int,
    ) -> None:
        """Notify the seller when a product crosses below the stock threshold."""
        self._post(
            "/notifications/low-stock",
            {
                "seller_id": seller_id,
                "product_id": str(product_id),
                "product_name": product_name,
                "current_stock": current_stock,
                "threshold": threshold,
            },
            product_id=product_id,
            event="low_stock",
        )

    def notify_out_of_stock(
        self,
        *,
        seller_id: str,
        product_id: UUID,
        product_name: str,
    ) -> None:
        """Notify the seller when a product reaches zero stock."""
        self._post(
            "/notifications/out-of-stock",
            {
                "seller_id": seller_id,
                "product_id": str(product_id),
                "product_name": product_name,
                "current_stock": 0,
            },
            product_id=product_id,
            event="out_of_stock",
        )

    def _post(self, path: str, payload: dict, *, product_id: UUID, event: str) -> None:
        base_url = self.settings.NOTIFICATIONS_SERVICE_URL.rstrip("/")
        if not base_url:
            return

        try:
            response = httpx.post(
                f"{base_url}{path}",
                json=payload,
                headers=build_observability_headers(),
                timeout=3.0,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning(
                "Notifications service failed for stock event: "
                "event=%s product=%s exc=%s",
                event,
                product_id,
                exc,
            )
