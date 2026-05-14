"""
Middleware Architecture
========================
Layered middleware stack applied in registration order (outermost first):
  1. RequestContextMiddleware  — assigns request_id, binds logging context
  2. RequestLoggingMiddleware  — logs every request/response with timing
  3. SecurityHeadersMiddleware — adds production-grade HTTP security headers
  4. CORSMiddleware            — registered separately via FastAPI helper

Design: all middleware is async-first and adds < 1ms overhead.
"""

import time
import uuid
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.logging import (
    bind_request_context,
    clear_request_context,
    get_logger,
)

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# 1. Request Context Middleware
# ──────────────────────────────────────────────

class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Assigns a unique request_id to every incoming request.
    Stores it on request.state and binds it to structlog's context vars
    so all downstream log calls automatically include it.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        bind_request_context(
            request_id=request_id,
            path=request.url.path,
            method=request.method,
        )

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            clear_request_context()


# ──────────────────────────────────────────────
# 2. Request Logging Middleware
# ──────────────────────────────────────────────

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every HTTP request with method, path, status, and duration.
    Skips noisy health-check endpoints to keep logs clean.
    """

    SKIP_PATHS = {"/health", "/api/v1/health", "/metrics", "/favicon.ico"}

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        log_fn = logger.warning if response.status_code >= 400 else logger.info

        log_fn(
            "http.request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            client_ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", ""),
        )

        response.headers["X-Response-Time"] = f"{duration_ms}ms"
        return response


# ──────────────────────────────────────────────
# 3. Security Headers Middleware
# ──────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Applies production-grade HTTP security headers to every response.
    Based on OWASP Secure Headers Project recommendations.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )

        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self';"
            )

        # Remove server fingerprinting
        response.headers.pop("server", None)
        response.headers.pop("x-powered-by", None)

        return response


# ──────────────────────────────────────────────
# Middleware Registration
# ──────────────────────────────────────────────

from app.core.middleware.csrf import CSRFMiddleware
from app.core.middleware.validation import RequestValidationMiddleware

def register_middleware(app: FastAPI) -> None:
    """
    Register all middleware on the FastAPI application.
    Order matters: middleware is applied bottom-up (last added = outermost).
    """

    # CORS (must be registered before custom middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.origins_list,
        allow_credentials=settings.cors.allow_credentials,
        allow_methods=["*"],
        allow_headers=["*", "X-CSRF-Token"],
        expose_headers=["X-Request-ID", "X-Response-Time"],
    )

    # Phase 2: security middleware
    app.add_middleware(RequestValidationMiddleware)
    app.add_middleware(CSRFMiddleware)

    # Phase 1: core middleware (applied outermost last)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestContextMiddleware)
