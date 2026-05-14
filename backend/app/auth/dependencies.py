"""
Authentication Dependencies
=============================
FastAPI dependency functions for extracting and validating the current user.
These are the building blocks for all protected endpoints.

Usage:
    @router.get("/me")
    async def get_me(current_user: User = Depends(get_current_active_user)):
        return current_user
"""

import uuid
from typing import Annotated, Optional

from fastapi import Cookie, Depends, Header, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.services.auth_service import AuthService
from app.auth.utils.tokens import decode_access_token, extract_bearer_token
from app.core.config import get_settings, AppSettings
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.db.cache import CacheClient, get_cache
from app.db.models.user import User, UserStatus
from app.db.repositories.user import UserRepository
from app.db.session import get_db


# ──────────────────────────────────────────────
# Service Factory Dependencies
# ──────────────────────────────────────────────

async def get_auth_service(
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_cache),
) -> AuthService:
    """Provide a fully wired AuthService instance per request."""
    cache_client = CacheClient(cache)
    return AuthService(session=db, cache=cache_client)


async def get_cache_client(cache: Redis = Depends(get_cache)) -> CacheClient:
    return CacheClient(cache)


# ──────────────────────────────────────────────
# Token Extraction
# ──────────────────────────────────────────────

async def get_token_from_request(
    authorization: Optional[str] = Header(default=None),
    access_token: Optional[str] = Cookie(default=None),
) -> str:
    """
    Extract JWT from Authorization header (Bearer) OR secure cookie.
    Header takes precedence over cookie.
    """
    if authorization:
        return extract_bearer_token(authorization)
    if access_token:
        return access_token
    raise UnauthorizedException("Authentication required. Provide a Bearer token or cookie.")


# ──────────────────────────────────────────────
# Current User Resolution
# ──────────────────────────────────────────────

async def get_current_user(
    token: str = Depends(get_token_from_request),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Decode access token and return the corresponding User.
    Raises UnauthorizedException if token is invalid or user not found.
    """
    payload = decode_access_token(token)
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthorizedException("Invalid token payload.")

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise UnauthorizedException("Invalid user ID in token.")

    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if not user:
        raise UnauthorizedException("User associated with this token no longer exists.")

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Ensure the current user's account is active and not locked.
    Use this for most protected endpoints.
    """
    if current_user.status == UserStatus.SUSPENDED:
        raise ForbiddenException("Your account has been suspended. Please contact support.")

    if current_user.is_locked:
        raise ForbiddenException(
            "Your account is temporarily locked. Please try again later."
        )

    if current_user.status == UserStatus.PENDING_VERIFICATION:
        raise ForbiddenException("Please verify your email address before accessing this resource.")

    if current_user.deleted_at is not None:
        raise UnauthorizedException("This account no longer exists.")

    return current_user


async def get_optional_user(
    authorization: Optional[str] = Header(default=None),
    access_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Optionally resolve the current user — returns None if not authenticated.
    Use for endpoints that work for both authenticated and anonymous users.
    """
    try:
        if not authorization and not access_token:
            return None
        token = extract_bearer_token(authorization) if authorization else access_token
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload.get("sub"))
        repo = UserRepository(db)
        return await repo.get_by_id(user_id)
    except Exception:
        return None


# ──────────────────────────────────────────────
# Convenience Type Aliases (for clean signatures)
# ──────────────────────────────────────────────

CurrentUser = Annotated[User, Depends(get_current_active_user)]
OptionalUser = Annotated[Optional[User], Depends(get_optional_user)]
