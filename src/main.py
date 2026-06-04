"""
Bazaar Inventory Service — Application entry-point.

Creates the FastAPI application, registers routers, and configures
structured logging.  Database tables are created on startup via the
ORM metadata (suitable for development; use Alembic migrations in
production).
"""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from src.api.exception_handlers import register_exception_handlers
from src.api.health import router as health_router
from src.api.routers.stock import router as stock_router
from src.core.config import get_settings
from src.core.database import Base, engine, wait_for_db
from src.core.logging import setup_logging
from src.core.observability import CorrelationIdMiddleware
from src.core.telemetry import initialize_prometheus_metrics, router as metrics_router
from src.models import Stock  # noqa: F401


settings = get_settings()
logger = logging.getLogger(__name__)

initialize_prometheus_metrics()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application startup / shutdown lifecycle hook."""
    setup_logging()
    logger.info("Starting %s", settings.APP_NAME)
    if not settings.CATALOG_SERVICE_URL:
        logger.warning(
            "CATALOG_SERVICE_URL is empty; catalog stock-status notifications are disabled"
        )
    wait_for_db()
    Base.metadata.create_all(bind=engine)
    yield
    logger.info("Shutting down %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(CorrelationIdMiddleware)


@app.middleware("http")
async def logging_middleware(request: Request, call_next) -> Response:  # type: ignore[type-arg]
    """Log method, path, status code and duration for every request."""
    start = time.monotonic()
    response: Response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "%s %s %d %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# ── Routers ──────────────────────────────────────────
app.include_router(health_router)
app.include_router(stock_router)
app.include_router(metrics_router)

# ── Exception handlers ────────────────────────────────
register_exception_handlers(app)
