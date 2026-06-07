"""
Stock route registrations for the inventory microservice.

All routes are under /internal/products — this service is NOT exposed
through the public gateway.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Response

from src.api.controllers.stock import StockController
from src.core.dependencies import DbSession
from src.schemas.error import ErrorResponse
from src.schemas.stock import (
    BatchStocksRequest,
    BatchStocksResponse,
    RegisterStockRequest,
    ReleaseStockRequest,
    ReleaseBatchRequest,
    ReserveBatchItem,
    ReserveStockRequest,
    StockResponse,
    UpdateStockRequest,
    CommitBatchRequest,
    CommitBatchResponse,
)


router = APIRouter(
    prefix="/internal/products",
    tags=["Stock"],
    responses={
        404: {"description": "Stock entry not found", "model": ErrorResponse},
    },
)


@router.post(
    "/stocks",
    response_model=BatchStocksResponse,
    summary="Batch query stock levels",
    description="Return current stock quantities for a list of product IDs.",
)
def get_stocks(
    payload: BatchStocksRequest,
    db: DbSession,
) -> BatchStocksResponse:
    return StockController(db).get_stocks(payload)


@router.post(
    "/{id}/stock",
    status_code=201,
    response_model=StockResponse,
    summary="Register initial stock",
    description="Create the stock entry for a product when it is first created.",
    responses={201: {"description": "Stock entry created"}},
)
def register_stock(
    id: UUID,
    payload: RegisterStockRequest,
    db: DbSession,
) -> StockResponse:
    return StockController(db).register_stock(id, payload)


@router.delete(
    "/{id}/stock",
    status_code=204,
    summary="Remove stock entry",
    description="Delete the stock entry when a product is removed.",
    responses={204: {"description": "Stock entry deleted"}},
)
def delete_stock(
    id: UUID,
    db: DbSession,
) -> Response:
    StockController(db).delete_stock(id)
    return Response(status_code=204)


@router.get(
    "/{id}/stock",
    response_model=StockResponse,
    summary="Get stock for a product",
    description="Return the current stock quantity for a single product.",
)
def get_stock(
    id: UUID,
    db: DbSession,
) -> StockResponse:
    return StockController(db).get_stock(id)


@router.put(
    "/{id}/stock",
    response_model=StockResponse,
    summary="Update stock level",
    description="Fully replace the stock level for a product (manual adjustment).",
)
def update_stock(
    id: UUID,
    payload: UpdateStockRequest,
    db: DbSession,
) -> StockResponse:
    return StockController(db).update_stock(id, payload)


@router.post(
    "/{id}/stock/reserve",
    response_model=StockResponse,
    summary="Reserve stock",
    description=(
        "Atomically decrement stock by the given quantity. "
        "Returns 409 if there is not enough stock available."
    ),
    responses={
        409: {"description": "Insufficient stock", "model": ErrorResponse},
    },
)
def reserve_stock(
    id: UUID,
    payload: ReserveStockRequest,
    db: DbSession,
) -> StockResponse:
    return StockController(db).reserve_stock(id, payload)


@router.post(
    "/{id}/stock/release",
    response_model=StockResponse,
    summary="Release reserved stock",
    description="Restore previously reserved stock (used on order cancellation).",
)
def release_stock(
    id: UUID,
    payload: ReleaseStockRequest,
    db: DbSession,
) -> StockResponse:
    return StockController(db).release_stock(id, payload)


@router.post(
    "/stock/reserve",
    response_model=BatchStocksResponse,
    summary="Reserve stock in batch",
    description="Atomically reserve stock for multiple products in one call.",
    responses={
        409: {"description": "Insufficient stock", "model": ErrorResponse},
    },
)
def reserve_stocks(
    payload: Annotated[list[ReserveBatchItem], Body(min_length=1)],
    db: DbSession,
) -> BatchStocksResponse:
    return StockController(db).reserve_stocks(payload)


@router.post(
    "/stock/release",
    response_model=BatchStocksResponse,
    summary="Release stock in batch",
    description="Restore reserved stock for multiple products in one call.",
)
def release_stocks(
    payload: ReleaseBatchRequest,
    db: DbSession,
) -> BatchStocksResponse:
    return StockController(db).release_stocks(payload)


@router.post(
    "/stock/commit",
    response_model=CommitBatchResponse,
    summary="Commit stock in batch",
    description="Finalize all reservations for a given order_id.",
    responses={
        404: {"description": "Reservation not found", "model": ErrorResponse},
    },
)
def commit_stocks(
    payload: CommitBatchRequest,
    db: DbSession,
) -> CommitBatchResponse:
    return StockController(db).commit_stocks(payload)
