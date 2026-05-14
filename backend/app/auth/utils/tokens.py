"""
JWT Token Management
======================
Handles creation and validation of access and refresh tokens.
Access tokens: short-lived (15 min default), stateless JWT.
Refresh tokens: long-lived (7 days), server-side validated via DB hash.

Token rotation strategy:
  - Each refresh issues a NEW refresh token and revokes the old one.
  - Tokens belong to a "family" (UUID). If a revoked token is reused,
    the entire family is invalidated — detecting token theft.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import UnauthorizedException
from app.core.logging import get_logger

logger = get_logger(__name__)

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


# ──────────────────────────────────────────────
# Token Creation
# ──────────────────────────────────────────────

def create_access_token(
    user_id: str,
    email: str,
    role: str,
    *,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> tuple[str, datetime]:
    """
    Create a signed JWT access token.
    Returns (token_string, expires_at).
    """
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.auth.access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "iat": datetime.now(timezone.utc),
        "exp": expires_at,
        "jti": str(uuid.uuid4()),          # JWT ID — unique per token
    }
    if extra_claims:
        payload.update(extra_claims)

    token = jwt.encode(
        payload,
        settings.auth.access_token_secret,
        algorithm=settings.auth.algorithm,
    )
    return token, expires_at


def create_refresh_token(
    user_id: str,
    *,
    family: Optional[str] = None,
) -> tuple[str, str, datetime]:
    """
    Create a signed JWT refresh token.
    Returns (token_string, family_id, expires_at).
    The family_id groups tokens for rotation/theft detection.
    """
    token_family = family or str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.auth.refresh_token_expire_days
    )
    payload = {
        "sub": str(user_id),
        "type": REFRESH_TOKEN_TYPE,
        "family": token_family,
        "iat": datetime.now(timezone.utc),
        "exp": expires_at,
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(
        payload,
        settings.auth.refresh_token_secret,
        algorithm=settings.auth.algorithm,
    )
    return token, token_family, expires_at


# ──────────────────────────────────────────────
# Token Validation
# ──────────────────────────────────────────────

def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate an access token.
    Raises UnauthorizedException on any validation failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.auth.access_token_secret,
            algorithms=[settings.auth.algorithm],
        )
        if payload.get("type") != ACCESS_TOKEN_TYPE:
            raise UnauthorizedException("Invalid token type.")
        return payload
    except JWTError as exc:
        logger.warning("jwt.decode_failed", token_type="access", error=str(exc))
        raise UnauthorizedException("Access token is invalid or expired.") from exc


def decode_refresh_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a refresh token.
    Raises UnauthorizedException on any validation failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.auth.refresh_token_secret,
            algorithms=[settings.auth.algorithm],
        )
        if payload.get("type") != REFRESH_TOKEN_TYPE:
            raise UnauthorizedException("Invalid token type.")
        return payload
    except JWTError as exc:
        logger.warning("jwt.decode_failed", token_type="refresh", error=str(exc))
        raise UnauthorizedException("Refresh token is invalid or expired.") from exc


def extract_bearer_token(authorization_header: Optional[str]) -> str:
    """
    Extract the token string from 'Bearer <token>' header.
    Raises UnauthorizedException if header is malformed.
    """
    if not authorization_header:
        raise UnauthorizedException("Authorization header is missing.")
    parts = authorization_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise UnauthorizedException("Authorization header must be 'Bearer <token>'.")
    return parts[1]
