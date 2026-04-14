"""
Shared pytest fixtures for the test suite.

Tests run against a **real PostgreSQL** database provided by
``docker-compose.test.yml``.  Connection details come from the
same environment variables the application uses (DB_HOST, DB_PORT,
DB_USER, DB_PASSWORD, DB_NAME).

**No mocking is used** — the inventory service has no external dependencies.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.core.database import Base, engine
from src.main import app


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    """Create all tables before the session and tear them down after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_database():
    """Truncate the stocks table between tests to keep cases isolated."""
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE stocks RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture()
def client() -> TestClient:
    """Return a ``TestClient`` bound to the FastAPI application."""
    return TestClient(app)
