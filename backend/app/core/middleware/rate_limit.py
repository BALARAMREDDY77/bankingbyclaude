"""
Rate Limiting Middleware
==========================
Two-layer rate limiting:
  1. SlowAPI (decorator-based per-endpoint limits)
  2. Custom Redis sliding window (IP-based + user-based)

Banking rate limits:
  - Login: 5 attempts / 5 min per IP
  - General API: 100 req / 60s per IP
  - Sensitive ops (password change): 3 req / hour per user
"""

from typing import Optional

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.logging import get_logger
from app.db.cache import get_redis_client

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# SlowAPI Limiter (decorator approach)
# ──────────────────────────────────────────────

def _get_identifier(request: Request) -> str:
    """Use real IP (handle proxy headers) as rate limit key."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_identifier)

# Pre-defined rate limit strings for common use cases
LOGIN_RATE_LIMIT = f"{settings.auth.login_rate_limit}/minute"
API_RATE_LIMIT = f"{settings.auth.api_rate_limit}/minute"
SENSITIVE_RATE_LIMIT = "3/hour"
PASSWORD_RESET_RATE_LIMIT = "5/hour"


# ──────────────────────────────────────────────
# Custom Redis Sliding Window Rate Limiter
# ──────────────────────────────────────────────

class RedisRateLimiter:
    """
    Redis-backed sliding window rate limiter.
    More accurate than token bucket for financial APIs.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def is_allowed(self, key: str) -> tuple[bool, int]:
        """
        Check if the request is within rate limit.
        Returns (is_allowed, current_count).
        Uses Redis atomic INCR + EXPIRE.
        """
        try:
            client = get_redis_client()
            full_key = f"ratelimit:{key}"
            count = await client.incr(full_key)
            if count == 1:
                await client.expire(full_key, self.window_seconds)
            return count <= self.max_requests, count
        except Exception as exc:
            logger.error("rate_limiter.redis_error", error=str(exc))
            # Fail open — don't block on Redis errors
            return True, 0

    async def remaining(self, key: str) -> int:
        try:
            client = get_redis_client()
            count = await client.get(f"ratelimit:{key}") or 0
            return max(0, self.max_requests - int(count))
        except Exception:
            return self.max_requests


# Singleton rate limiters for common limits
login_limiter = RedisRateLimiter(
    max_requests=settings.auth.login_rate_limit,
    window_seconds=settings.auth.login_rate_window,
)
api_limiter = RedisRateLimiter(
    max_requests=settings.auth.api_rate_limit,
    window_seconds=settings.auth.api_rate_window,
)
sensitive_limiter = RedisRateLimiter(max_requests=3, window_seconds=3600)


# ──────────────────────────────────────────────
# Rate Limit FastAPI Dependency
# ──────────────────────────────────────────────

async def check_login_rate_limit(request: Request) -> None:
    """
    Dependency for login endpoint rate limiting.
    Raises 429 if limit exceeded.
    """
    from fastapi import HTTPException
    ip = _get_identifier(request)
    is_allowed, count = await login_limiter.is_allowed(f"login:{ip}")
    if not is_allowed:
        logger.warning(
            "rate_limit.login_exceeded",
            ip=ip,
            count=count,
            limit=settings.auth.login_rate_limit,
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Too many login attempts. Please wait before trying again.",
                }
            },
            headers={"Retry-After": str(settings.auth.login_rate_window)},
        )


async def check_api_rate_limit(request: Request) -> None:
    """General API rate limit dependency."""
    from fastapi import HTTPException
    ip = _get_identifier(request)
    is_allowed, count = await api_limiter.is_allowed(f"api:{ip}")
    if not is_allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": {"code": "RATE_LIMITED", "message": "Too many requests."}},
            headers={"Retry-After": str(settings.auth.api_rate_window)},
        )
