"""
Pydantic schemas for stock API contracts.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StockSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: UUID
    quantity: int
    updated_at: datetime


class StockResponse(BaseModel):
    data: StockSchema


class RegisterStockRequest(BaseModel):
    quantity: int = Field(ge=0)


class UpdateStockRequest(BaseModel):
    quantity: int = Field(ge=0)


class ReserveStockRequest(BaseModel):
    quantity: int = Field(ge=1)


class ReleaseStockRequest(BaseModel):
    quantity: int = Field(ge=1)


class BatchStocksRequest(BaseModel):
    product_ids: list[UUID] = Field(min_length=1)


class BatchStocksResponse(BaseModel):
    data: dict[str, int]
