"""
FastAPI exception handlers for the inventory microservice.

All error responses follow RFC 7807 (application/problem+json).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.exceptions.stock import InsufficientStock, StockNotFound


def _problem(
    request: Request,
    status: int,
    title: str,
    detail: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": request.url.path,
        },
        media_type="application/problem+json",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all domain exception handlers to *app*."""

    @app.exception_handler(StockNotFound)
    async def stock_not_found_handler(
        request: Request, exc: StockNotFound
    ) -> JSONResponse:
        return _problem(
            request,
            404,
            "Not Found",
            f"Stock for product {exc.product_id} not found",
        )

    @app.exception_handler(InsufficientStock)
    async def insufficient_stock_handler(
        request: Request, exc: InsufficientStock
    ) -> JSONResponse:
        return _problem(
            request,
            409,
            "Insufficient Stock",
            f"Product {exc.product_id} has only {exc.available} units available.",
        )
