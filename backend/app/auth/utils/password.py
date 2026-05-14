"""
Password Security Utilities
=============================
Bcrypt hashing with configurable work factor.
All password operations are async-friendly (run_in_executor for CPU-bound ops).
"""

import asyncio
import secrets
import string
from functools import partial

from passlib.context import CryptContext

from app.core.config import settings

# Configure passlib with bcrypt
_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=settings.auth.bcrypt_rounds,
)


async def hash_password(plain_password: str) -> str:
    """
    Hash a plain-text password using bcrypt.
    Runs in a thread pool to avoid blocking the event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, partial(_pwd_context.hash, plain_password)
    )


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify plain-text password against stored bcrypt hash.
    Runs in a thread pool — bcrypt is intentionally CPU-intensive.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, partial(_pwd_context.verify, plain_password, hashed_password)
    )


def generate_secure_token(length: int = 32) -> str:
    """Generate a cryptographically secure random token (URL-safe)."""
    return secrets.token_urlsafe(length)


def generate_numeric_otp(length: int = 6) -> str:
    """Generate a numeric OTP (for SMS / email verification)."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def validate_password_strength(password: str) -> tuple[bool, list[str]]:
    """
    Validate password meets banking-grade strength requirements.
    Returns (is_valid, list_of_violations).
    """
    violations = []

    if len(password) < 12:
        violations.append("Password must be at least 12 characters long.")
    if len(password) > 128:
        violations.append("Password must not exceed 128 characters.")
    if not any(c.isupper() for c in password):
        violations.append("Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in password):
        violations.append("Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in password):
        violations.append("Password must contain at least one digit.")
    if not any(c in string.punctuation for c in password):
        violations.append("Password must contain at least one special character.")

    # Common weak passwords
    common_patterns = ["password", "123456", "qwerty", "banking", "admin"]
    if any(p in password.lower() for p in common_patterns):
        violations.append("Password contains a commonly used pattern.")

    return len(violations) == 0, violations
