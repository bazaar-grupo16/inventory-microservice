"""
Integration tests for all stock endpoints.

Every test runs against a real PostgreSQL database — no mocking.
The database is provided by docker-compose.test.yml.
"""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from src.services.notifications import NotificationsService


# ── Helpers ───────────────────────────────────────────────────────────────────


def register(client: TestClient, product_id=None, quantity: int = 10):
    """POST /internal/products/{id}/stock and return the response."""
    pid = product_id or uuid4()
    response = client.post(
        f"/internal/products/{pid}/stock",
        json={"quantity": quantity},
    )
    return pid, response


# ── POST /internal/products/{id}/stock ───────────────────────────────────────


class TestRegisterStock:
    """Register initial stock for a new product."""

    def test_creates_stock_entry_and_returns_201(self, client: TestClient) -> None:
        pid, response = register(client, quantity=50)

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["product_id"] == str(pid)
        assert data["quantity"] == 50

    def test_accepts_zero_initial_stock(self, client: TestClient) -> None:
        _, response = register(client, quantity=0)

        assert response.status_code == 201
        assert response.json()["data"]["quantity"] == 0

    def test_rejects_negative_quantity(self, client: TestClient) -> None:
        pid = uuid4()
        response = client.post(
            f"/internal/products/{pid}/stock",
            json={"quantity": -1},
        )

        assert response.status_code == 422


# ── DELETE /internal/products/{id}/stock ─────────────────────────────────────


class TestDeleteStock:
    """Remove stock entry when a product is deleted."""

    def test_returns_204_on_success(self, client: TestClient) -> None:
        pid, _ = register(client)

        response = client.delete(f"/internal/products/{pid}/stock")

        assert response.status_code == 204
        assert response.content == b""

    def test_deleted_entry_is_no_longer_retrievable(self, client: TestClient) -> None:
        pid, _ = register(client)
        client.delete(f"/internal/products/{pid}/stock")

        response = client.get(f"/internal/products/{pid}/stock")

        assert response.status_code == 404

    def test_returns_404_for_nonexistent_product(self, client: TestClient) -> None:
        pid = uuid4()

        response = client.delete(f"/internal/products/{pid}/stock")

        assert response.status_code == 404
        body = response.json()
        assert body["type"] == "about:blank"
        assert body["status"] == 404


# ── GET /internal/products/{id}/stock ────────────────────────────────────────


class TestGetStock:
    """Retrieve current stock for a single product."""

    def test_returns_current_quantity(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=25)

        response = client.get(f"/internal/products/{pid}/stock")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["product_id"] == str(pid)
        assert data["quantity"] == 25

    def test_returns_404_for_nonexistent_product(self, client: TestClient) -> None:
        pid = uuid4()

        response = client.get(f"/internal/products/{pid}/stock")

        assert response.status_code == 404
        body = response.json()
        assert body["type"] == "about:blank"
        assert body["title"] == "Not Found"
        assert body["status"] == 404
        assert body["instance"] == f"/internal/products/{pid}/stock"


# ── POST /internal/products/stocks ───────────────────────────────────────────


class TestGetStocksBatch:
    """Batch query stock levels for multiple products."""

    def test_returns_quantities_for_all_requested_ids(self, client: TestClient) -> None:
        pid_a, _ = register(client, quantity=5)
        pid_b, _ = register(client, quantity=15)

        response = client.post(
            "/internal/products/stocks",
            json={"product_ids": [str(pid_a), str(pid_b)]},
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data[str(pid_a)] == 5
        assert data[str(pid_b)] == 15

    def test_omits_ids_with_no_stock_entry(self, client: TestClient) -> None:
        pid_known, _ = register(client, quantity=3)
        pid_unknown = uuid4()

        response = client.post(
            "/internal/products/stocks",
            json={"product_ids": [str(pid_known), str(pid_unknown)]},
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert str(pid_known) in data
        assert str(pid_unknown) not in data

    def test_rejects_empty_product_ids_list(self, client: TestClient) -> None:
        response = client.post(
            "/internal/products/stocks",
            json={"product_ids": []},
        )

        assert response.status_code == 422


# ── PUT /internal/products/{id}/stock ────────────────────────────────────────


class TestUpdateStock:
    """Full replacement of stock level (manual adjustment)."""

    def test_replaces_stock_quantity(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)

        response = client.put(
            f"/internal/products/{pid}/stock",
            json={"quantity": 99},
        )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 99

    def test_allows_setting_stock_to_zero(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=5)

        response = client.put(
            f"/internal/products/{pid}/stock",
            json={"quantity": 0},
        )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 0

    def test_returns_404_for_nonexistent_product(self, client: TestClient) -> None:
        response = client.put(
            f"/internal/products/{uuid4()}/stock",
            json={"quantity": 10},
        )

        assert response.status_code == 404

    def test_rejects_negative_quantity(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)

        response = client.put(
            f"/internal/products/{pid}/stock",
            json={"quantity": -5},
        )

        assert response.status_code == 422

    def test_notifies_low_stock_when_crossing_threshold(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = []
        pid, _ = register(client, quantity=10)

        def fake_notify_low_stock(self, **kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(
            NotificationsService,
            "notify_low_stock",
            fake_notify_low_stock,
        )

        response = client.put(
            f"/internal/products/{pid}/stock",
            json={
                "quantity": 3,
                "seller_id": "seller-123",
                "product_name": "Auriculares",
            },
        )

        assert response.status_code == 200
        assert calls == [
            {
                "seller_id": "seller-123",
                "product_id": pid,
                "product_name": "Auriculares",
                "current_stock": 3,
                "threshold": 5,
            }
        ]

    def test_does_not_notify_low_stock_without_metadata(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = []
        pid, _ = register(client, quantity=10)

        def fake_notify_low_stock(self, **kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(
            NotificationsService,
            "notify_low_stock",
            fake_notify_low_stock,
        )

        response = client.put(
            f"/internal/products/{pid}/stock",
            json={"quantity": 3},
        )

        assert response.status_code == 200
        assert calls == []


# ── POST /internal/products/{id}/stock/reserve ───────────────────────────────


class TestReserveStock:
    """Atomic stock reservation for the checkout flow."""

    def test_decrements_stock_by_requested_quantity(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)

        response = client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 3},
        )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 7

    def test_allows_reserving_all_remaining_stock(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=5)

        response = client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 5},
        )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 0

    def test_returns_409_when_stock_is_insufficient(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=2)

        response = client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 3},
        )

        assert response.status_code == 409
        body = response.json()
        assert body["type"] == "about:blank"
        assert body["title"] == "Insufficient Stock"
        assert body["status"] == 409
        assert str(pid) in body["detail"]
        assert body["instance"] == f"/internal/products/{pid}/stock/reserve"

    def test_returns_409_when_stock_is_zero(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=0)

        response = client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 1},
        )

        assert response.status_code == 409

    def test_returns_404_for_nonexistent_product(self, client: TestClient) -> None:
        response = client.post(
            f"/internal/products/{uuid4()}/stock/reserve",
            json={"quantity": 1},
        )

        assert response.status_code == 404

    def test_rejects_zero_quantity(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)

        response = client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 0},
        )

        assert response.status_code == 422

    def test_stock_unchanged_after_failed_reservation(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=2)
        client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 5},
        )

        response = client.get(f"/internal/products/{pid}/stock")

        assert response.json()["data"]["quantity"] == 2

    def test_notifies_out_of_stock_when_crossing_to_zero(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = []
        pid, _ = register(client, quantity=5)

        def fake_notify_out_of_stock(self, **kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(
            NotificationsService,
            "notify_out_of_stock",
            fake_notify_out_of_stock,
        )

        response = client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={
                "quantity": 5,
                "seller_id": "seller-123",
                "product_name": "Auriculares",
            },
        )

        assert response.status_code == 200
        assert calls == [
            {
                "seller_id": "seller-123",
                "product_id": pid,
                "product_name": "Auriculares",
            }
        ]

    def test_notifications_failure_does_not_break_stock_update(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pid, _ = register(client, quantity=10)

        def fake_notify_low_stock(self, **kwargs):
            raise RuntimeError("notifications unavailable")

        monkeypatch.setattr(
            NotificationsService,
            "notify_low_stock",
            fake_notify_low_stock,
        )

        response = client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={
                "quantity": 7,
                "seller_id": "seller-123",
                "product_name": "Auriculares",
            },
        )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 3


# ── POST /internal/products/{id}/stock/release ───────────────────────────────


class TestReleaseStock:
    """Restore reserved stock on order cancellation."""

    def test_increments_stock_by_released_quantity(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)
        client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 4},
        )

        response = client.post(
            f"/internal/products/{pid}/stock/release",
            json={"quantity": 4},
        )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 10

    def test_release_restores_partial_quantity(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)
        client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 6},
        )

        response = client.post(
            f"/internal/products/{pid}/stock/release",
            json={"quantity": 3},
        )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 7

    def test_returns_404_for_nonexistent_product(self, client: TestClient) -> None:
        response = client.post(
            f"/internal/products/{uuid4()}/stock/release",
            json={"quantity": 1},
        )

        assert response.status_code == 404

    def test_rejects_zero_quantity(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)

        response = client.post(
            f"/internal/products/{pid}/stock/release",
            json={"quantity": 0},
        )

        assert response.status_code == 422


# ── POST /internal/products/stock/reserve ────────────────────────────────────


class TestBatchReserveStock:
    """Atomic batch reservation for checkout flows."""

    def test_reserves_multiple_products_atomically(self, client: TestClient) -> None:
        pid_a, _ = register(client, quantity=10)
        pid_b, _ = register(client, quantity=4)

        response = client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid_a), "quantity": 3},
                {"product_id": str(pid_b), "quantity": 4},
            ],
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data[str(pid_a)] == 7
        assert data[str(pid_b)] == 0

    def test_fails_and_reports_all_out_of_stock_products(
        self, client: TestClient
    ) -> None:
        pid_a, _ = register(client, quantity=2)
        pid_b, _ = register(client, quantity=1)

        response = client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid_a), "quantity": 1},
                {"product_id": str(pid_b), "quantity": 3},
                {"product_id": str(uuid4()), "quantity": 2},
            ],
        )

        assert response.status_code == 409
        body = response.json()
        assert body["type"] == "about:blank"
        assert body["title"] == "Insufficient Stock"
        assert body["status"] == 409
        assert str(pid_b) in body["detail"]
        assert body["instance"] == "/internal/products/stock/reserve"

    def test_batch_reserve_is_atomic_on_failure(self, client: TestClient) -> None:
        pid_a, _ = register(client, quantity=5)
        pid_b, _ = register(client, quantity=2)

        response = client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid_a), "quantity": 3},
                {"product_id": str(pid_b), "quantity": 5},
            ],
        )

        assert response.status_code == 409

        stock_a = client.get(f"/internal/products/{pid_a}/stock")
        stock_b = client.get(f"/internal/products/{pid_b}/stock")
        assert stock_a.json()["data"]["quantity"] == 5
        assert stock_b.json()["data"]["quantity"] == 2


# ── POST /internal/products/stock/release ────────────────────────────────────


class TestBatchReleaseStock:
    """Restore reserved stock for multiple products."""

    def test_releases_multiple_products(self, client: TestClient) -> None:
        pid_a, _ = register(client, quantity=10)
        pid_b, _ = register(client, quantity=6)
        client.post(
            f"/internal/products/{pid_a}/stock/reserve",
            json={"quantity": 4},
        )
        client.post(
            f"/internal/products/{pid_b}/stock/reserve",
            json={"quantity": 2},
        )

        response = client.post(
            "/internal/products/stock/release",
            json=[
                {"product_id": str(pid_a), "quantity": 3},
                {"product_id": str(pid_b), "quantity": 2},
            ],
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data[str(pid_a)] == 9
        assert data[str(pid_b)] == 6

    def test_rejects_empty_batch(self, client: TestClient) -> None:
        response = client.post(
            "/internal/products/stock/release",
            json=[],
        )

        assert response.status_code == 422


class TestCatalogNotifications:
    """Catalog notifications are emitted only on zero-threshold crossings."""

    def test_reserve_to_zero_notifies_no_stock(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=5)

        with patch("src.services.catalog.CatalogService.notify_stock_status") as notify:
            response = client.post(
                f"/internal/products/{pid}/stock/reserve",
                json={"quantity": 5},
            )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 0
        notify.assert_called_once_with(pid, has_stock=False)

    def test_reserve_above_zero_does_not_notify(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=5)

        with patch("src.services.catalog.CatalogService.notify_stock_status") as notify:
            response = client.post(
                f"/internal/products/{pid}/stock/reserve",
                json={"quantity": 2},
            )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 3
        notify.assert_not_called()

    def test_release_from_zero_notifies_has_stock(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=0)

        with patch("src.services.catalog.CatalogService.notify_stock_status") as notify:
            response = client.post(
                f"/internal/products/{pid}/stock/release",
                json={"quantity": 4},
            )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 4
        notify.assert_called_once_with(pid, has_stock=True)

    def test_release_above_zero_does_not_notify(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=3)

        with patch("src.services.catalog.CatalogService.notify_stock_status") as notify:
            response = client.post(
                f"/internal/products/{pid}/stock/release",
                json={"quantity": 2},
            )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 5
        notify.assert_not_called()

    def test_update_to_zero_notifies_no_stock(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=3)

        with patch("src.services.catalog.CatalogService.notify_stock_status") as notify:
            response = client.put(
                f"/internal/products/{pid}/stock",
                json={"quantity": 0},
            )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 0
        notify.assert_called_once_with(pid, has_stock=False)

    def test_update_from_zero_notifies_has_stock(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=0)

        with patch("src.services.catalog.CatalogService.notify_stock_status") as notify:
            response = client.put(
                f"/internal/products/{pid}/stock",
                json={"quantity": 5},
            )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 5
        notify.assert_called_once_with(pid, has_stock=True)

    def test_update_nonzero_to_nonzero_does_not_notify(
        self, client: TestClient
    ) -> None:
        pid, _ = register(client, quantity=3)

        with patch("src.services.catalog.CatalogService.notify_stock_status") as notify:
            response = client.put(
                f"/internal/products/{pid}/stock",
                json={"quantity": 5},
            )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 5
        notify.assert_not_called()

    def test_catalog_failure_does_not_fail_reserve(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=5)

        with patch(
            "src.services.catalog.CatalogService.notify_stock_status",
            side_effect=RuntimeError("catalog unavailable"),
        ) as notify:
            response = client.post(
                f"/internal/products/{pid}/stock/reserve",
                json={"quantity": 5},
            )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 0
        notify.assert_called_once_with(pid, has_stock=False)
