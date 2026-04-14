"""
Stock controller — wires repository and service, handles request/response mapping.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from src.dtos import (
    BatchStocksDTO,
    RegisterStockDTO,
    ReleaseStockDTO,
    ReserveStockDTO,
    UpdateStockDTO,
)
from src.repositories.stock import StockRepository
from src.schemas.stock import (
    BatchStocksRequest,
    BatchStocksResponse,
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
        dto = UpdateStockDTO(product_id=product_id, quantity=payload.quantity)
        stock = self.service.update_stock(dto)
        return StockResponse(data=stock)

    def reserve_stock(
        self, product_id: UUID, payload: ReserveStockRequest
    ) -> StockResponse:
        dto = ReserveStockDTO(product_id=product_id, quantity=payload.quantity)
        stock = self.service.reserve_stock(dto)
        return StockResponse(data=stock)

    def release_stock(
        self, product_id: UUID, payload: ReleaseStockRequest
    ) -> StockResponse:
        dto = ReleaseStockDTO(product_id=product_id, quantity=payload.quantity)
        stock = self.service.release_stock(dto)
        return StockResponse(data=stock)
