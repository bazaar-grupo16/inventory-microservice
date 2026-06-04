"""
Stock controller — wires repository and service, handles request/response mapping.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from src.dtos import (
    BatchStocksDTO,
    BatchStockQuantityRequestDTO,
    RegisterStockDTO,
    ReleaseStockDTO,
    ReserveStockDTO,
    StockNotificationMetadataDTO,
    StockQuantityRequestDTO,
    UpdateStockDTO,
)
from src.repositories.stock import StockRepository
from src.services.catalog import CatalogService
from src.services.notifications import NotificationsService
from src.schemas.stock import (
    BatchStocksRequest,
    BatchStocksResponse,
    BatchStockChangeRequest,
    RegisterStockRequest,
    ReleaseStockRequest,
    ReserveStockRequest,
    StockResponse,
    UpdateStockRequest,
)
from src.services.stock import StockService


class StockController:
    """Instantiates the repository and service, maps HTTP input to DTOs and
    ORM results back to response schemas."""

    def __init__(self, db: Session) -> None:
        self.service = StockService(
            repository=StockRepository(db),
            catalog_service=CatalogService(),
            notifications_service=NotificationsService(),
        )

    def register_stock(
        self, product_id: UUID, payload: RegisterStockRequest
    ) -> StockResponse:
        dto = RegisterStockDTO(product_id=product_id, quantity=payload.quantity)
        stock = self.service.register_stock(dto)
        return StockResponse(data=stock)

    def delete_stock(self, product_id: UUID) -> None:
        self.service.delete_stock(product_id)

    def get_stock(self, product_id: UUID) -> StockResponse:
        stock = self.service.get_stock(product_id)
        return StockResponse(data=stock)

    def get_stocks(self, payload: BatchStocksRequest) -> BatchStocksResponse:
        dto = BatchStocksDTO(product_ids=payload.product_ids)
        stocks = self.service.get_stocks(dto)
        return BatchStocksResponse(data={str(k): v for k, v in stocks.items()})

    def update_stock(
        self, product_id: UUID, payload: UpdateStockRequest
    ) -> StockResponse:
        dto = UpdateStockDTO(
            product_id=product_id,
            quantity=payload.quantity,
            notification_metadata=_notification_metadata(payload),
        )
        stock = self.service.update_stock(dto)
        return StockResponse(data=stock)

    def reserve_stock(
        self, product_id: UUID, payload: ReserveStockRequest
    ) -> StockResponse:
        dto = ReserveStockDTO(
            product_id=product_id,
            quantity=payload.quantity,
            notification_metadata=_notification_metadata(payload),
        )
        stock = self.service.reserve_stock(dto)
        return StockResponse(data=stock)

    def release_stock(
        self, product_id: UUID, payload: ReleaseStockRequest
    ) -> StockResponse:
        dto = ReleaseStockDTO(product_id=product_id, quantity=payload.quantity)
        stock = self.service.release_stock(dto)
        return StockResponse(data=stock)

    def reserve_stocks(
        self, payload: list[BatchStockChangeRequest]
    ) -> BatchStocksResponse:
        dto = BatchStockQuantityRequestDTO(
            items=[_stock_quantity_request_dto(item) for item in payload]
        )
        stocks = self.service.reserve_stocks(dto)
        return BatchStocksResponse(data={str(k): v for k, v in stocks.items()})

    def release_stocks(
        self, payload: list[BatchStockChangeRequest]
    ) -> BatchStocksResponse:
        dto = BatchStockQuantityRequestDTO(
            items=[
                StockQuantityRequestDTO(product_id=item.product_id, quantity=item.quantity)
                for item in payload
            ]
        )
        stocks = self.service.release_stocks(dto)
        return BatchStocksResponse(data={str(k): v for k, v in stocks.items()})


def _notification_metadata(payload) -> StockNotificationMetadataDTO | None:
    """Return notification metadata when both optional fields are present."""
    seller_id = getattr(payload, "seller_id", None)
    product_name = getattr(payload, "product_name", None)
    if not seller_id or not product_name:
        return None
    return StockNotificationMetadataDTO(
        seller_id=seller_id,
        product_name=product_name,
    )


def _stock_quantity_request_dto(
    item: BatchStockChangeRequest,
) -> StockQuantityRequestDTO:
    """Map a batch stock request item to its service DTO."""
    return StockQuantityRequestDTO(
        product_id=item.product_id,
        quantity=item.quantity,
        notification_metadata=_notification_metadata(item),
    )
