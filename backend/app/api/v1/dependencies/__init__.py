"""
Dependency Injection Container
================================
Centralizes all reusable FastAPI dependencies.
Import from here — not from the underlying modules — to maintain
a single authoritative source for dependency wiring.

Usage in endpoints:
    from app.api.v1.dependencies import get_db, get_cache, get_settings

    @router.get("/")
    async def endpoint(
        db: AsyncSession = Depends(get_db),
        cache: Redis = Depends(get_cache),
        settings: AppSettings = Depends(get_settings),
    ): ...
"""

from app.core.config import get_settings
from app.db.session import get_db
from app.db.cache import get_cache

__all__ = [
    "get_settings",
    "get_db",
    "get_cache",
]
