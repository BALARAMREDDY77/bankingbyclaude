"""
Redis Cache Infrastructure
============================
Async Redis client with connection pool management.
Provides a clean interface for caching, session storage, and pub/sub.
"""

from typing import Any, Optional
import json

import redis.asyncio as aioredis
from redis.asyncio import Redis, ConnectionPool

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level pool (initialized at startup)
_pool: Optional[ConnectionPool] = None
_client: Optional[Redis] = None


async def connect_redis() -> None:
    """Initialize the Redis connection pool at application startup."""
    global _pool, _client
    try:
        _pool = aioredis.ConnectionPool.from_url(
            settings.redis.url,
            max_connections=settings.redis.max_connections,
            decode_responses=True,
        )
        _client = aioredis.Redis(connection_pool=_pool)
        await _client.ping()
        logger.info("redis.connected", host=settings.redis.host)
    except Exception as exc:
        logger.error("redis.connection_failed", error=str(exc))
        raise


async def disconnect_redis() -> None:
    """Close all Redis connections gracefully at shutdown."""
    global _pool, _client
    if _client:
        await _client.aclose()
    if _pool:
        await _pool.aclose()
    logger.info("redis.disconnected")


def get_redis_client() -> Redis:
    """Return the active Redis client. Raises if not initialized."""
    if _client is None:
        raise RuntimeError("Redis client is not initialized. Call connect_redis() first.")
    return _client


# ──────────────────────────────────────────────
# FastAPI Dependency
# ──────────────────────────────────────────────

async def get_cache() -> Redis:
    """
    FastAPI dependency for injecting the Redis client.

    Usage:
        @router.get("/")
        async def endpoint(cache: Redis = Depends(get_cache)):
            await cache.set("key", "value", ex=300)
    """
    return get_redis_client()


# ──────────────────────────────────────────────
# Cache Helpers
# ──────────────────────────────────────────────

class CacheClient:
    """
    High-level async cache client wrapping raw Redis.
    Handles JSON serialization and TTL management.
    """

    def __init__(self, client: Redis, prefix: str = "banking") -> None:
        self.client = client
        self.prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    async def get(self, key: str) -> Optional[Any]:
        raw = await self.client.get(self._key(key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        serialized = json.dumps(value) if not isinstance(value, str) else value
        result = await self.client.setex(self._key(key), ttl_seconds, serialized)
        return bool(result)

    async def delete(self, key: str) -> bool:
        result = await self.client.delete(self._key(key))
        return bool(result)

    async def exists(self, key: str) -> bool:
        result = await self.client.exists(self._key(key))
        return bool(result)

    async def increment(self, key: str, amount: int = 1) -> int:
        return await self.client.incrby(self._key(key), amount)

    async def set_with_nx(self, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        """Set only if key does not exist (atomic distributed lock primitive)."""
        serialized = json.dumps(value) if not isinstance(value, str) else value
        result = await self.client.set(
            self._key(key), serialized, ex=ttl_seconds, nx=True
        )
        return result is not None
