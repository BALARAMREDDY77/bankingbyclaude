"""
FastAPI Application Factory
=============================
Creates and configures the FastAPI application instance.
Uses the factory pattern so the app can be tested with different configs.

Startup sequence:
  1. Configure structured logging
  2. Register middleware stack
  3. Register exception handlers
  4. Connect to PostgreSQL
  5. Connect to Redis
  6. Include API routers

Shutdown sequence:
  1. Disconnect from PostgreSQL
  2. Disconnect from Redis
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.api.v1 import api_v1_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import register_middleware
from app.db.cache import connect_redis, disconnect_redis
from app.db.session import connect_db, disconnect_db

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Lifespan (startup + shutdown)
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──────────────────────────────
    configure_logging()
    logger.info(
        "application.starting",
        name=settings.app_name,
        version=settings.app_version,
        env=settings.app_env.value,
    )

    await connect_db()
    await connect_redis()

    logger.info("application.ready")
    yield

    # ── SHUTDOWN ─────────────────────────────
    logger.info("application.shutting_down")
    await disconnect_db()
    await disconnect_redis()
    logger.info("application.stopped")


# ──────────────────────────────────────────────
# Application Factory
# ──────────────────────────────────────────────

def create_application() -> FastAPI:
    """
    Create and fully configure the FastAPI application.
    Called once at process startup.
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Enterprise AI Banking Platform — Production-grade API "
            "with agentic AI capabilities."
        ),
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        default_response_class=ORJSONResponse,  # Faster JSON serialization
        lifespan=lifespan,
    )

    # Register in order: middleware → exception handlers → routers
    register_middleware(app)
    register_exception_handlers(app)

    # API v1
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)

    return app


# ──────────────────────────────────────────────
# ASGI Application Instance
# ──────────────────────────────────────────────

app: FastAPI = create_application()
