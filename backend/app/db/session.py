"""
Async Database Infrastructure
===============================
Sets up SQLAlchemy async engine, session factory, and declarative base.
All database access uses async/await — never blocking calls.

Connection pooling is pre-configured for production workloads.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Declarative Base
# ──────────────────────────────────────────────

class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.
    Extend this in domain model files.
    """
    pass


# ──────────────────────────────────────────────
# Engine & Session Factory
# ──────────────────────────────────────────────

def create_engine() -> AsyncEngine:
    db = settings.database
    return create_async_engine(
        db.async_url,
        echo=db.echo,
        pool_size=db.pool_size,
        max_overflow=db.max_overflow,
        pool_timeout=db.pool_timeout,
        pool_pre_ping=True,                # Detect stale connections
        pool_recycle=3600,                 # Recycle connections every hour
    )


# Module-level engine and factory (created once at import)
engine: AsyncEngine = create_engine()

AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,                # Keep objects usable after commit
    autocommit=False,
    autoflush=False,
)


# ──────────────────────────────────────────────
# Session Context Manager (for use outside DI)
# ──────────────────────────────────────────────

@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for manual DB session management.
    Use this in background tasks, startup hooks, scripts, etc.

    Example:
        async with get_db_session() as session:
            result = await session.execute(select(User))
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ──────────────────────────────────────────────
# FastAPI Dependency
# ──────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for injecting an async DB session.

    Usage:
        @router.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ──────────────────────────────────────────────
# Lifecycle Helpers
# ──────────────────────────────────────────────

async def connect_db() -> None:
    """Test DB connection at startup — fail fast if unreachable."""
    try:
        async with engine.begin() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        logger.info("database.connected", url=settings.database.host)
    except Exception as exc:
        logger.error("database.connection_failed", error=str(exc))
        raise


async def disconnect_db() -> None:
    """Gracefully dispose the connection pool on shutdown."""
    await engine.dispose()
    logger.info("database.disconnected")
