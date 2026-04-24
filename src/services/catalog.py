"""
HTTP client for communicating stock-status changes to catalog.
"""

from __future__ import annotations

import logging
from uuid import UUID

import httpx

from src.core.config import get_settings


logger = logging.getLogger(__name__)


class CatalogService:
    """Best-effort client for inventory -> catalog stock notifications."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def notify_stock_status(self, product_id: UUID, has_stock: bool) -> None:
        """Notify catalog when a product crosses the zero-stock threshold."""
        base_url = self.settings.CATALOG_SERVICE_URL.rstrip("/")
        if not base_url:
            return

        url = f"{base_url}/internal/products/{product_id}/stock-status"

        try:
            response = httpx.patch(
                url,
                json={"has_stock": has_stock},
                timeout=3.0,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning(
                "Catalog stock-status notification failed for product %s: %s",
                product_id,
                exc,
            )
