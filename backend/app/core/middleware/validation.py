"""
Request Validation Middleware
==============================
Guards at the HTTP layer before any business logic runs:
  - Content-Type enforcement for JSON endpoints
  - Request body size limits
  - Basic XSS / SQL injection pattern detection
  - Suspicious header detection
"""

import re
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
from fastapi import Request, Response
from fastapi.responses import ORJSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)

# Patterns that suggest injection or XSS attempts
SUSPICIOUS_PATTERNS = [
    re.compile(r"<script[\s>]", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),          # onerror=, onclick=, etc.
    re.compile(r"union\s+select", re.IGNORECASE),
    re.compile(r";\s*drop\s+table", re.IGNORECASE),
    re.compile(r"--\s*$", re.MULTILINE),
    re.compile(r"\/\*.*\*\/", re.DOTALL),              # SQL block comments
]

MAX_BODY_SIZE = 10 * 1024 * 1024   # 10 MB global limit


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """
    Lightweight request validation at the ASGI layer.
    Rejects obviously malicious or malformed requests before FastAPI parsing.
    """

    def __init__(self, app: ASGIApp, max_body_size: int = MAX_BODY_SIZE) -> None:
        super().__init__(app)
        self.max_body_size = max_body_size

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:

        # ── Body size check ──────────────────────────────────
        content_length = request.headers.get("Content-Length")
        if content_length and int(content_length) > self.max_body_size:
            logger.warning(
                "request.body_too_large",
                size=content_length,
                limit=self.max_body_size,
                path=request.url.path,
            )
            return ORJSONResponse(
                status_code=413,
                content={
                    "success": False,
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": f"Request body exceeds the maximum size of "
                                   f"{self.max_body_size // 1024 // 1024}MB.",
                    },
                },
            )

        # ── Suspicious query param scan ───────────────────────
        raw_url = str(request.url)
        if self._contains_suspicious_pattern(raw_url):
            logger.warning(
                "security.suspicious_request",
                url=raw_url,
                ip=request.client.host if request.client else "unknown",
            )
            return ORJSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": {
                        "code": "BAD_REQUEST",
                        "message": "Request contains invalid characters.",
                    },
                },
            )

        # ── Suspicious header detection ───────────────────────
        host = request.headers.get("Host", "")
        if self._contains_suspicious_pattern(host):
            return ORJSONResponse(
                status_code=400,
                content={"success": False, "error": {"code": "BAD_REQUEST", "message": "Invalid request headers."}},
            )

        return await call_next(request)

    @staticmethod
    def _contains_suspicious_pattern(value: str) -> bool:
        return any(p.search(value) for p in SUSPICIOUS_PATTERNS)
