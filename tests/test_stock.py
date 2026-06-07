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

from src.core.cleanup import release_expired_reservations
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
        order_id = uuid4()

        response = client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 3, "order_id": str(order_id)},
        )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 7

        # Check reservations table
        from src.core.database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT quantity FROM reservations WHERE order_id = :order_id AND product_id = :product_id"),
                {"order_id": order_id, "product_id": pid}
            ).fetchone()
            assert row is not None
            assert row[0] == 3

    def test_reserve_idempotent(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)
        order_id = uuid4()

        payload = {"quantity": 3, "order_id": str(order_id)}
        res1 = client.post(f"/internal/products/{pid}/stock/reserve", json=payload)
        assert res1.status_code == 200
        assert res1.json()["data"]["quantity"] == 7

        res2 = client.post(f"/internal/products/{pid}/stock/reserve", json=payload)
        assert res2.status_code == 200
        assert res2.json()["data"]["quantity"] == 7

    def test_allows_reserving_all_remaining_stock(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=5)
        order_id = uuid4()

        response = client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 5, "order_id": str(order_id)},
        )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 0

    def test_returns_409_when_stock_is_insufficient(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=2)
        order_id = uuid4()

        response = client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 3, "order_id": str(order_id)},
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
        order_id = uuid4()

        response = client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 1, "order_id": str(order_id)},
        )

        assert response.status_code == 409

    def test_returns_404_for_nonexistent_product(self, client: TestClient) -> None:
        response = client.post(
            f"/internal/products/{uuid4()}/stock/reserve",
            json={"quantity": 1, "order_id": str(uuid4())},
        )

        assert response.status_code == 404

    def test_rejects_zero_quantity(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)

        response = client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 0, "order_id": str(uuid4())},
        )

        assert response.status_code == 422

    def test_stock_unchanged_after_failed_reservation(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=2)
        client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 5, "order_id": str(uuid4())},
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
                "order_id": str(uuid4()),
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
                "order_id": str(uuid4()),
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
        order_id = uuid4()
        client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 4, "order_id": str(order_id)},
        )

        response = client.post(
            f"/internal/products/{pid}/stock/release",
            json={"order_id": str(order_id)},
        )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 10

        # Assert reservation row deleted
        from src.core.database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM reservations WHERE order_id = :order_id AND product_id = :product_id"),
                {"order_id": order_id, "product_id": pid}
            ).scalar()
            assert count == 0

    def test_release_is_idempotent(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)
        order_id = uuid4()
        client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 6, "order_id": str(order_id)},
        )

        response = client.post(
            f"/internal/products/{pid}/stock/release",
            json={"order_id": str(order_id)},
        )
        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 10

        # Release again
        response2 = client.post(
            f"/internal/products/{pid}/stock/release",
            json={"order_id": str(order_id)},
        )
        assert response2.status_code == 200
        assert response2.json()["data"]["quantity"] == 10

    def test_returns_404_for_nonexistent_product(self, client: TestClient) -> None:
        response = client.post(
            f"/internal/products/{uuid4()}/stock/release",
            json={"order_id": str(uuid4())},
        )

        assert response.status_code == 404

    def test_rejects_missing_order_id(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)

        response = client.post(
            f"/internal/products/{pid}/stock/release",
            json={},
        )

        assert response.status_code == 422


# ── POST /internal/products/stock/reserve ────────────────────────────────────


class TestBatchReserveStock:
    """Atomic batch reservation for checkout flows."""

    def test_reserves_multiple_products_atomically(self, client: TestClient) -> None:
        pid_a, _ = register(client, quantity=10)
        pid_b, _ = register(client, quantity=4)
        order_id = uuid4()
        response = client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid_a), "quantity": 3, "order_id": str(order_id)},
                {"product_id": str(pid_b), "quantity": 4, "order_id": str(order_id)},
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
        order_id = uuid4()

        response = client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid_a), "quantity": 1, "order_id": str(order_id)},
                {"product_id": str(pid_b), "quantity": 3, "order_id": str(order_id)},
                {"product_id": str(uuid4()), "quantity": 2, "order_id": str(order_id)},
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
        order_id = uuid4()

        response = client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid_a), "quantity": 3, "order_id": str(order_id)},
                {"product_id": str(pid_b), "quantity": 5, "order_id": str(order_id)},
            ],
        )

        assert response.status_code == 409

        stock_a = client.get(f"/internal/products/{pid_a}/stock")
        stock_b = client.get(f"/internal/products/{pid_b}/stock")
        assert stock_a.json()["data"]["quantity"] == 5
        assert stock_b.json()["data"]["quantity"] == 2

    def test_batch_reserve_atomic_rollback(self, client: TestClient) -> None:
        # Reserve 2 products where the 2nd has insufficient stock -> assert 409, 
        # assert BOTH stocks.quantity values are unchanged, assert zero rows in reservations for that order_id
        pid_a, _ = register(client, quantity=10)
        pid_b, _ = register(client, quantity=2)
        order_id = uuid4()

        response = client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid_a), "quantity": 3, "order_id": str(order_id)},
                {"product_id": str(pid_b), "quantity": 5, "order_id": str(order_id)},
            ],
        )

        assert response.status_code == 409

        # Assert BOTH stocks.quantity values are unchanged (10 and 2)
        stock_a = client.get(f"/internal/products/{pid_a}/stock").json()["data"]["quantity"]
        stock_b = client.get(f"/internal/products/{pid_b}/stock").json()["data"]["quantity"]
        assert stock_a == 10
        assert stock_b == 2

        # Assert zero rows in reservations for that order_id
        from src.core.database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM reservations WHERE order_id = :order_id"),
                {"order_id": order_id}
            ).scalar()
            assert count == 0

    def test_batch_reserve_idempotent(self, client: TestClient) -> None:
        pid_a, _ = register(client, quantity=10)
        pid_b, _ = register(client, quantity=5)
        order_id = uuid4()

        payload = [
            {"product_id": str(pid_a), "quantity": 3, "order_id": str(order_id)},
            {"product_id": str(pid_b), "quantity": 2, "order_id": str(order_id)},
        ]

        # First reserve
        res1 = client.post("/internal/products/stock/reserve", json=payload)
        assert res1.status_code == 200
        assert res1.json()["data"][str(pid_a)] == 7
        assert res1.json()["data"][str(pid_b)] == 3

        # Second reserve (idempotent call)
        res2 = client.post("/internal/products/stock/reserve", json=payload)
        assert res2.status_code == 200
        # Stock remains at 7 and 3
        assert res2.json()["data"][str(pid_a)] == 7
        assert res2.json()["data"][str(pid_b)] == 3


# ── POST /internal/products/stock/release ────────────────────────────────────


class TestBatchReleaseStock:
    """Restore reserved stock for multiple products."""

    def test_releases_product_by_order_id(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)
        order_id = uuid4()

        # Reserve stock via batch reserve, which creates a reservation
        res = client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid), "quantity": 4, "order_id": str(order_id)},
            ],
        )
        assert res.status_code == 200
        assert res.json()["data"][str(pid)] == 6

        # Release stock via batch release
        response = client.post(
            "/internal/products/stock/release",
            json={"order_id": str(order_id)},
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data[str(pid)] == 10

    def test_rejects_invalid_release_request(self, client: TestClient) -> None:
        response = client.post(
            "/internal/products/stock/release",
            json={},
        )

        assert response.status_code == 422

    def test_release_unknown_order_id_returns_200_and_stock_unchanged(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)

        response = client.post(
            "/internal/products/stock/release",
            json={"order_id": str(uuid4())},
        )

        assert response.status_code == 200
        assert response.json()["data"] == {}

        # Verify stock remains unchanged
        stock_res = client.get(f"/internal/products/{pid}/stock")
        assert stock_res.json()["data"]["quantity"] == 10

    def test_double_release_returns_200_both_times_and_stock_restored_once(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=10)
        order_id = uuid4()

        # Reserve
        client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid), "quantity": 4, "order_id": str(order_id)},
            ],
        )

        # First release: stock restored
        response1 = client.post(
            "/internal/products/stock/release",
            json={"order_id": str(order_id)},
        )
        assert response1.status_code == 200
        assert response1.json()["data"][str(pid)] == 10

        # Second release: stock remains 10 (not 14), returns 200 with empty data
        response2 = client.post(
            "/internal/products/stock/release",
            json={"order_id": str(order_id)},
        )
        assert response2.status_code == 200
        assert response2.json()["data"] == {}

        # Verify stock is indeed 10
        stock_res = client.get(f"/internal/products/{pid}/stock")
        assert stock_res.json()["data"]["quantity"] == 10

    def test_batch_release_idempotent(self, client: TestClient) -> None:
        # Call batch release twice with the same order_id -> both return 200, stock restored exactly once
        pid, _ = register(client, quantity=10)
        order_id = uuid4()

        # Reserve
        client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid), "quantity": 4, "order_id": str(order_id)},
            ],
        )

        # First release
        res1 = client.post(
            "/internal/products/stock/release",
            json={"order_id": str(order_id)},
        )
        assert res1.status_code == 200
        assert res1.json()["data"][str(pid)] == 10

        # Second release
        res2 = client.post(
            "/internal/products/stock/release",
            json={"order_id": str(order_id)},
        )
        assert res2.status_code == 200
        assert res2.json()["data"] == {}

        # Stock is still 10, not 14
        stock = client.get(f"/internal/products/{pid}/stock").json()["data"]["quantity"]
        assert stock == 10


class TestCommitStock:

    def test_commit_success(self, client: TestClient) -> None:
        # Reserve then commit -> reservations table has zero rows for that order_id, stocks.quantity unchanged
        pid_a, _ = register(client, quantity=10)
        pid_b, _ = register(client, quantity=5)
        order_id = uuid4()

        # Reserve
        res = client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid_a), "quantity": 3, "order_id": str(order_id)},
                {"product_id": str(pid_b), "quantity": 2, "order_id": str(order_id)},
            ],
        )
        assert res.status_code == 200

        # Commit
        response = client.post(
            "/internal/products/stock/commit",
            json={"order_id": str(order_id)},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["order_id"] == str(order_id)
        assert set(data["committed_products"]) == {str(pid_a), str(pid_b)}

        # Reservations table has zero rows for that order_id
        from src.core.database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM reservations WHERE order_id = :order_id"),
                {"order_id": order_id}
            ).scalar()
            assert count == 0

        # Stock quantity remains at the decremented values (7 and 3)
        stock_a = client.get(f"/internal/products/{pid_a}/stock").json()["data"]["quantity"]
        stock_b = client.get(f"/internal/products/{pid_b}/stock").json()["data"]["quantity"]
        assert stock_a == 7
        assert stock_b == 3

    def test_commit_not_found(self, client: TestClient) -> None:
        # Commit with unknown order_id -> 404
        response = client.post(
            "/internal/products/stock/commit",
            json={"order_id": str(uuid4())},
        )
        assert response.status_code == 404
        assert response.json()["title"] == "Reservation Not Found"

class TestCatalogNotifications:
    """Catalog notifications are emitted only on zero-threshold crossings."""

    def test_reserve_to_zero_notifies_no_stock(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=5)

        with patch("src.services.catalog.CatalogService.notify_stock_status") as notify:
            response = client.post(
                f"/internal/products/{pid}/stock/reserve",
                json={"quantity": 5, "order_id": str(uuid4())},
            )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 0
        notify.assert_called_once_with(pid, has_stock=False)

    def test_reserve_above_zero_does_not_notify(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=5)

        with patch("src.services.catalog.CatalogService.notify_stock_status") as notify:
            response = client.post(
                f"/internal/products/{pid}/stock/reserve",
                json={"quantity": 2, "order_id": str(uuid4())},
            )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 3
        notify.assert_not_called()

    def test_release_from_zero_notifies_has_stock(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=4)
        order_id = uuid4()
        client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 4, "order_id": str(order_id)},
        )

        with patch("src.services.catalog.CatalogService.notify_stock_status") as notify:
            response = client.post(
                f"/internal/products/{pid}/stock/release",
                json={"order_id": str(order_id)},
            )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 4
        notify.assert_called_once_with(pid, has_stock=True)

    def test_release_above_zero_does_not_notify(self, client: TestClient) -> None:
        pid, _ = register(client, quantity=5)
        order_id = uuid4()
        client.post(
            f"/internal/products/{pid}/stock/reserve",
            json={"quantity": 2, "order_id": str(order_id)},
        )

        with patch("src.services.catalog.CatalogService.notify_stock_status") as notify:
            response = client.post(
                f"/internal/products/{pid}/stock/release",
                json={"order_id": str(order_id)},
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
                json={"quantity": 5, "order_id": str(uuid4())},
            )

        assert response.status_code == 200
        assert response.json()["data"]["quantity"] == 0
        notify.assert_called_once_with(pid, has_stock=False)


# ── Concurrency Tests ─────────────────────────────────────────────────────────


class TestConcurrentStockReservation:
    """Validate pessimistic locking and stock limits under concurrent requests."""

    def test_concurrent_reservation_quantity_one(self, client: TestClient) -> None:
        import concurrent.futures

        pid, _ = register(client, quantity=1)

        def make_request():
            try:
                response = client.post(
                    f"/internal/products/{pid}/stock/reserve",
                    json={"quantity": 1, "order_id": str(uuid4())},
                )
                return response.status_code, response.json()
            except Exception as e:
                return 500, str(e)

        # Launch two threads concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(make_request) for _ in range(2)]
            results = [f.result() for f in futures]

        status_codes = [r[0] for r in results]

        # Exactly one should succeed (200), and one should fail (409)
        assert 200 in status_codes
        assert 409 in status_codes

        # Verify final stock is 0
        final_stock_res = client.get(f"/internal/products/{pid}/stock")
        assert final_stock_res.json()["data"]["quantity"] == 0

    def test_concurrent_reservation_quantity_not_negative(self, client: TestClient) -> None:
        import concurrent.futures

        pid, _ = register(client, quantity=1)

        def make_request():
            try:
                response = client.post(
                    f"/internal/products/{pid}/stock/reserve",
                    json={"quantity": 1, "order_id": str(uuid4())},
                )
                return response.status_code
            except Exception:
                return 500

        # Launch 10 concurrent requests
        num_requests = 10
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_requests) as executor:
            futures = [executor.submit(make_request) for _ in range(num_requests)]
            status_codes = [f.result() for f in futures]

        # Exactly one should be 200, others 409
        success_count = status_codes.count(200)
        failure_count = status_codes.count(409)

        assert success_count == 1
        assert failure_count == num_requests - 1

        # Final stock in DB must be exactly 0
        final_stock_res = client.get(f"/internal/products/{pid}/stock")
        final_quantity = final_stock_res.json()["data"]["quantity"]
        assert final_quantity == 0

    def test_concurrent_reservation_high_volume(self, client: TestClient) -> None:
        import concurrent.futures

        pid, _ = register(client, quantity=100)

        def make_request():
            try:
                response = client.post(
                    f"/internal/products/{pid}/stock/reserve",
                    json={"quantity": 10, "order_id": str(uuid4())},
                )
                return response.status_code
            except Exception:
                return 500

        # Launch 100 concurrent requests
        num_requests = 100
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_requests) as executor:
            futures = [executor.submit(make_request) for _ in range(num_requests)]
            status_codes = [f.result() for f in futures]

        # Exactly 10 should be 200, others 409
        success_count = status_codes.count(200)
        failure_count = status_codes.count(409)

        assert success_count == 10
        assert failure_count == num_requests - 10

        # Final stock in DB must be exactly 0
        final_stock_res = client.get(f"/internal/products/{pid}/stock")
        final_quantity = final_stock_res.json()["data"]["quantity"]
        assert final_quantity == 0

    def test_concurrent_batch_reserve(self, client: TestClient) -> None:
        import concurrent.futures
        pid_a, _ = register(client, quantity=10)
        pid_b, _ = register(client, quantity=5)
        order_id = uuid4()

        def make_request():
            try:
                response = client.post(
                    "/internal/products/stock/reserve",
                    json=[
                        {"product_id": str(pid_a), "quantity": 3, "order_id": str(order_id)},
                        {"product_id": str(pid_b), "quantity": 2, "order_id": str(order_id)},
                    ],
                )
                return response.status_code
            except Exception:
                return 500

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(make_request) for _ in range(2)]
            status_codes = [f.result() for f in futures]

        assert status_codes[0] == 200
        assert status_codes[1] == 200

        stock_a = client.get(f"/internal/products/{pid_a}/stock").json()["data"]["quantity"]
        stock_b = client.get(f"/internal/products/{pid_b}/stock").json()["data"]["quantity"]
        assert stock_a == 7
        assert stock_b == 3

    def test_concurrent_batch_reserve_high_volume(self, client: TestClient) -> None:
        import concurrent.futures
        pid_a, _ = register(client, quantity=100)
        pid_b, _ = register(client, quantity=50)
        order_id = uuid4()

        def make_request():
            try:
                response = client.post(
                    "/internal/products/stock/reserve",
                    json=[
                        {"product_id": str(pid_a), "quantity": 2, "order_id": str(order_id)},
                        {"product_id": str(pid_b), "quantity": 1, "order_id": str(order_id)},
                    ],
                )
                return response.status_code
            except Exception:
                return 500

        num_requests = 30
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_requests) as executor:
            futures = [executor.submit(make_request) for _ in range(num_requests)]
            status_codes = [f.result() for f in futures]

        assert all(code == 200 for code in status_codes)

        stock_a = client.get(f"/internal/products/{pid_a}/stock").json()["data"]["quantity"]
        stock_b = client.get(f"/internal/products/{pid_b}/stock").json()["data"]["quantity"]
        assert stock_a == 98
        assert stock_b == 49

    def test_concurrent_batch_commit(self, client: TestClient) -> None:
        import concurrent.futures
        pid_a, _ = register(client, quantity=10)
        order_id = uuid4()

        # Reserve
        client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid_a), "quantity": 3, "order_id": str(order_id)},
            ],
        )

        def make_request():
            try:
                response = client.post(
                    "/internal/products/stock/commit",
                    json={"order_id": str(order_id)},
                )
                return response.status_code
            except Exception:
                return 500

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(make_request) for _ in range(2)]
            status_codes = [f.result() for f in futures]

        assert sorted(status_codes) == [200, 404]

    def test_concurrent_batch_commit_high_volume(self, client: TestClient) -> None:
        import concurrent.futures
        pid_a, _ = register(client, quantity=10)
        order_id = uuid4()

        # Reserve
        client.post(
            "/internal/products/stock/reserve",
            json=[
                {"product_id": str(pid_a), "quantity": 3, "order_id": str(order_id)},
            ],
        )

        def make_request():
            try:
                response = client.post(
                    "/internal/products/stock/commit",
                    json={"order_id": str(order_id)},
                )
                return response.status_code
            except Exception:
                return 500

        num_requests = 20
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_requests) as executor:
            futures = [executor.submit(make_request) for _ in range(num_requests)]
            status_codes = [f.result() for f in futures]

        assert status_codes.count(200) == 1
        assert status_codes.count(404) == num_requests - 1

    def test_concurrent_batch_reserve_different_orders(self, client: TestClient) -> None:
        import concurrent.futures
        pid_a, _ = register(client, quantity=10)
        pid_b, _ = register(client, quantity=5)

        def make_request(order_id, qty_a, qty_b):
            try:
                response = client.post(
                    "/internal/products/stock/reserve",
                    json=[
                        {"product_id": str(pid_a), "quantity": qty_a, "order_id": str(order_id)},
                        {"product_id": str(pid_b), "quantity": qty_b, "order_id": str(order_id)},
                    ],
                )
                return response.status_code
            except Exception:
                return 500

        order_1 = uuid4()
        order_2 = uuid4()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(make_request, order_1, 6, 3),
                executor.submit(make_request, order_2, 5, 3),
            ]
            status_codes = [f.result() for f in futures]

        # Exactly one should succeed (200) and one should fail (409)
        assert sorted(status_codes) == [200, 409]

        stock_a = client.get(f"/internal/products/{pid_a}/stock").json()["data"]["quantity"]
        stock_b = client.get(f"/internal/products/{pid_b}/stock").json()["data"]["quantity"]

        if status_codes[0] == 200:
            assert stock_a == 4
            assert stock_b == 2
        else:
            assert stock_a == 5
            assert stock_b == 2

    def test_concurrent_batch_reserve_different_orders_high_volume(self, client: TestClient) -> None:
        import concurrent.futures
        pid, _ = register(client, quantity=100)

        def make_request(order_id):
            try:
                response = client.post(
                    "/internal/products/stock/reserve",
                    json=[
                        {"product_id": str(pid), "quantity": 5, "order_id": str(order_id)},
                    ],
                )
                return response.status_code
            except Exception:
                return 500

        num_requests = 30
        orders = [uuid4() for _ in range(num_requests)]

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_requests) as executor:
            futures = [executor.submit(make_request, order) for order in orders]
            status_codes = [f.result() for f in futures]

        # Exactly 20 should succeed (200) and 10 should fail (409)
        assert status_codes.count(200) == 20
        assert status_codes.count(409) == 10

        stock = client.get(f"/internal/products/{pid}/stock").json()["data"]["quantity"]
        assert stock == 0

    def test_concurrent_batch_commit_different_orders(self, client: TestClient) -> None:
        import concurrent.futures
        pid_a, _ = register(client, quantity=10)
        order_1 = uuid4()
        order_2 = uuid4()

        client.post(
            "/internal/products/stock/reserve",
            json=[{"product_id": str(pid_a), "quantity": 2, "order_id": str(order_1)}],
        )
        client.post(
            "/internal/products/stock/reserve",
            json=[{"product_id": str(pid_a), "quantity": 3, "order_id": str(order_2)}],
        )

        def make_request(order_id):
            try:
                response = client.post(
                    "/internal/products/stock/commit",
                    json={"order_id": str(order_id)},
                )
                return response.status_code
            except Exception:
                return 500

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(make_request, order_1),
                executor.submit(make_request, order_2),
            ]
            status_codes = [f.result() for f in futures]

        assert status_codes == [200, 200]

    def test_concurrent_batch_commit_different_orders_high_volume(self, client: TestClient) -> None:
        import concurrent.futures
        pid_a, _ = register(client, quantity=100)
        num_requests = 30
        orders = [uuid4() for _ in range(num_requests)]

        for order in orders:
            client.post(
                "/internal/products/stock/reserve",
                json=[{"product_id": str(pid_a), "quantity": 2, "order_id": str(order)}],
            )

        def make_request(order_id):
            try:
                response = client.post(
                    "/internal/products/stock/commit",
                    json={"order_id": str(order_id)},
                )
                return response.status_code
            except Exception:
                return 500

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_requests) as executor:
            futures = [executor.submit(make_request, order) for order in orders]
            status_codes = [f.result() for f in futures]

        assert all(code == 200 for code in status_codes)


@pytest.fixture
def db():
    from src.core.database import SessionLocal
    with SessionLocal() as session:
        yield session


def setup_expired_reservation(client, db, product_id, order_id, quantity=10, reserve_qty=3, expired=True):
    from datetime import timedelta
    from sqlalchemy import select
    from src.core.utils import utc_now
    from src.models.reservation import Reservation

    # Register stock via API
    client.post(f"/internal/products/{product_id}/stock", json={"quantity": quantity})
    # Reserve stock via API
    client.post(
        f"/internal/products/{product_id}/stock/reserve",
        json={"quantity": reserve_qty, "order_id": str(order_id)},
    )
    
    # Backdate or far-future the reservation
    res = db.scalar(
        select(Reservation)
        .where(
            Reservation.order_id == order_id,
            Reservation.product_id == product_id,
        )
    )
    if expired:
        res.expires_at = utc_now() - timedelta(minutes=1)
    else:
        res.expires_at = utc_now() + timedelta(minutes=60)
    db.add(res)
    db.commit()


class TestReservationCleanup:
    """Tests for background reservation expiry and cleanup task."""

    def test_expired_reservation_is_released(self, client, db):
        from sqlalchemy import select
        from src.models.stock import Stock
        from src.models.reservation import Reservation

        pid = uuid4()
        oid = uuid4()
        
        # 1. Setup an expired reservation (quantity=10, reserved=3, expired=True)
        setup_expired_reservation(client, db, pid, oid, quantity=10, reserve_qty=3, expired=True)
        
        # 2. Run cleanup
        released = release_expired_reservations(db)
        assert released == 1
        
        # 3. Assert reservation is gone
        res_count = db.scalar(
            select(Reservation)
            .where(Reservation.order_id == oid, Reservation.product_id == pid)
        )
        assert res_count is None
        
        # 4. Assert stock is restored to 10
        stock = db.scalar(select(Stock).where(Stock.product_id == pid))
        assert stock.quantity == 10

    def test_non_expired_reservation_is_not_released(self, client, db):
        from sqlalchemy import select
        from src.models.stock import Stock
        from src.models.reservation import Reservation

        pid = uuid4()
        oid = uuid4()
        
        # 1. Setup a non-expired reservation (quantity=10, reserved=3, expired=False)
        setup_expired_reservation(client, db, pid, oid, quantity=10, reserve_qty=3, expired=False)
        
        # 2. Run cleanup
        released = release_expired_reservations(db)
        assert released == 0
        
        # 3. Assert reservation still exists
        res = db.scalar(
            select(Reservation)
            .where(Reservation.order_id == oid, Reservation.product_id == pid)
        )
        assert res is not None
        assert res.quantity == 3
        
        # 4. Assert stock is still 7 (unchanged)
        stock = db.scalar(select(Stock).where(Stock.product_id == pid))
        assert stock.quantity == 7

    def test_cleanup_is_idempotent(self, client, db):
        from sqlalchemy import select
        from src.models.stock import Stock

        pid = uuid4()
        oid = uuid4()
        
        # 1. Setup an expired reservation
        setup_expired_reservation(client, db, pid, oid, quantity=10, reserve_qty=3, expired=True)
        
        # 2. Run cleanup first time
        released_1 = release_expired_reservations(db)
        assert released_1 == 1
        
        # 3. Run cleanup second time
        released_2 = release_expired_reservations(db)
        assert released_2 == 0
        
        # 4. Assert stock is restored to 10 (not 13 or something else)
        stock = db.scalar(select(Stock).where(Stock.product_id == pid))
        assert stock.quantity == 10