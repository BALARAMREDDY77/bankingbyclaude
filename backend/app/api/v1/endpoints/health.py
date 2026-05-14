"""
Health Check Endpoints
========================
Provides liveness and readiness probes for container orchestration.

GET /api/v1/health         — Basic liveness (returns 200 if process is alive)
GET /api/v1/health/ready   — Readiness (checks DB, Redis connectivity)
GET /api/v1/health/info    — App version/environment info
"""

import time
from typing import Dict, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
import sqlalchemy

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db
from app.db.cache import get_cache

logger = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])

_startup_time = time.time()


# ──────────────────────────────────────────────
# Liveness Probe
# ──────────────────────────────────────────────

@router.get(
    "",
    summary="Liveness probe",
    description="Returns 200 if the process is running. Used by load balancers.",
    status_code=status.HTTP_200_OK,
)
async def liveness() -> Dict[str, Any]:
    return {
        "status": "alive",
        "uptime_seconds": round(time.time() - _startup_time, 2),
    }


# ──────────────────────────────────────────────
# Readiness Probe
# ──────────────────────────────────────────────

@router.get(
    "/ready",
    summary="Readiness probe",
    description="Checks DB and Redis. Returns 503 if any dependency is unhealthy.",
)
async def readiness(
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_cache),
) -> ORJSONResponse:
    checks: Dict[str, Any] = {}
    all_healthy = True

    # --- Database check ---
    try:
        await db.execute(sqlalchemy.text("SELECT 1"))
        checks["database"] = {"status": "healthy"}
    except Exception as exc:
        logger.error("health.db_check_failed", error=str(exc))
        checks["database"] = {"status": "unhealthy", "error": str(exc)}
        all_healthy = False

    # --- Redis check ---
    try:
        await cache.ping()
        checks["redis"] = {"status": "healthy"}
    except Exception as exc:
        logger.error("health.redis_check_failed", error=str(exc))
        checks["redis"] = {"status": "unhealthy", "error": str(exc)}
        all_healthy = False

    http_status = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return ORJSONResponse(
        status_code=http_status,
        content={
            "status": "ready" if all_healthy else "not_ready",
            "checks": checks,
            "uptime_seconds": round(time.time() - _startup_time, 2),
        },
    )


# ──────────────────────────────────────────────
# Info Endpoint
# ──────────────────────────────────────────────

@router.get(
    "/info",
    summary="Application info",
    description="Returns app name, version, and environment. Disabled in production.",
)
async def info() -> Dict[str, Any]:
    # In production, hide internals
    if settings.is_production:
        return {"status": "ok"}

    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env.value,
        "api_prefix": settings.api_v1_prefix,
        "docs_enabled": settings.docs_enabled,
        "uptime_seconds": round(time.time() - _startup_time, 2),
    }
