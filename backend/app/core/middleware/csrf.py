"""
CSRF Protection
================
Double-submit cookie pattern for CSRF protection.
- Server generates a CSRF token and sets it as a non-HttpOnly cookie.
- Client must echo it back in the X-CSRF-Token header.
- Server compares cookie value vs header value.

Applied to state-changing endpoints (POST, PUT, PATCH, DELETE).
Skipped for: JSON API clients that send Authorization: Bearer header
(SameSite=Lax cookies + Bearer tokens naturally prevent CSRF).
"""

import hmac
import secrets

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"

# Endpoints excluded from CSRF (public endpoints, Bearer-only)
CSRF_EXEMPT_PREFIXES = [
    "/api/v1/health",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/auth/email/verify",
    "/api/v1/auth/password/reset",
    "/docs",
    "/redoc",
    "/openapi.json",
]

STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_serializer = URLSafeTimedSerializer(settings.auth.csrf_secret)


def generate_csrf_token() -> str:
    """Generate a signed, time-limited CSRF token."""
    random_value = secrets.token_urlsafe(32)
    return _serializer.dumps(random_value)


def validate_csrf_token(token: str, max_age: int = 3600) -> bool:
    """Validate a signed CSRF token. Returns False if invalid/expired."""
    try:
        _serializer.loads(token, max_age=max_age)
        return True
    except (BadSignature, Exception):
        return False


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF double-submit cookie middleware.
    Only applies to state-changing requests that use cookie-based auth.
    Requests with Authorization: Bearer header are exempt (API clients).
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Set CSRF cookie on all responses (if not already set)
        response = await self._handle_request(request, call_next)
        if not request.cookies.get(CSRF_COOKIE_NAME):
            token = generate_csrf_token()
            response.set_cookie(
                CSRF_COOKIE_NAME,
                token,
                httponly=False,           # Must be JS-readable for double-submit
                secure=settings.auth.cookie_secure,
                samesite="lax",
                max_age=settings.auth.csrf_token_expire_seconds,
            )
        return response

    async def _handle_request(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip CSRF check for safe methods
        if request.method not in STATE_CHANGING_METHODS:
            return await call_next(request)

        # Skip CSRF check for Bearer token clients (SPA API mode)
        if request.headers.get("Authorization", "").startswith("Bearer "):
            return await call_next(request)

        # Skip exempt paths
        path = request.url.path
        if any(path.startswith(prefix) for prefix in CSRF_EXEMPT_PREFIXES):
            return await call_next(request)

        # Validate CSRF
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
        header_token = request.headers.get(CSRF_HEADER_NAME)

        if not cookie_token or not header_token:
            from app.core.logging import get_logger
            logger.warning(
                "security.csrf_missing",
                path=path,
                method=request.method,
                has_cookie=bool(cookie_token),
                has_header=bool(header_token),
            )
            from fastapi.responses import ORJSONResponse
            return ORJSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "error": {
                        "code": "CSRF_VIOLATION",
                        "message": "CSRF token is missing.",
                    },
                },
            )

        # Compare tokens (constant-time comparison)
        if not hmac.compare_digest(cookie_token, header_token):
            logger.warning("security.csrf_mismatch", path=path)
            from fastapi.responses import ORJSONResponse
            return ORJSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "error": {
                        "code": "CSRF_VIOLATION",
                        "message": "CSRF token mismatch.",
                    },
                },
            )

        return await call_next(request)
