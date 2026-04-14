"""
Internal Data Transfer Objects for the inventory microservice.

DTOs carry validated data between the API layer and the service layer.
They have no validation logic — all validation happens in the Pydantic
schemas before the DTO is constructed.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass
class RegisterStockDTO:
    product_id: UUID
    quantity: int


@dataclass
class UpdateStockDTO:
    product_id: UUID
    quantity: int


@dataclass
class ReserveStockDTO:
    product_id: UUID
    quantity: int


@dataclass
class ReleaseStockDTO:
    product_id: UUID
    quantity: int


@dataclass
class BatchStocksDTO:
    product_ids: list[UUID]
