"""
Authentication Service
=======================
Central service for all authentication operations.
Business logic lives here — repositories handle DB, tokens handle JWT.

Operations:
  - register_user
  - authenticate_user (login)
  - refresh_access_token
  - logout / logout_everywhere
  - change_password
  - request_password_reset
  - complete_password_reset
  - verify_email
  - detect_suspicious_login
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.utils.password import (
    generate_secure_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.auth.utils.tokens import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from app.core.config import settings
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.core.logging import get_logger
from app.db.cache import CacheClient
from app.db.models.user import AuditEventType, User, UserRole, UserStatus
from app.db.repositories.user import AuditLogRepository, RefreshTokenRepository, UserRepository

logger = get_logger(__name__)


class AuthService:
    """
    Centralizes all auth business logic.
    Injected with session + cache per request via FastAPI DI.
    """

    def __init__(self, session: AsyncSession, cache: CacheClient) -> None:
        self.session = session
        self.cache = cache
        self.user_repo = UserRepository(session)
        self.token_repo = RefreshTokenRepository(session)
        self.audit_repo = AuditLogRepository(session)

    # ──────────────────────────────────────────
    # User Registration
    # ──────────────────────────────────────────

    async def register_user(
        self,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        role: UserRole = UserRole.CUSTOMER,
        phone: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> User:
        # Validate password strength
        is_strong, violations = validate_password_strength(password)
        if not is_strong:
            raise BadRequestException(
                message="Password does not meet security requirements.",
                detail=violations,
            )

        # Check email uniqueness
        if await self.user_repo.email_exists(email):
            raise ConflictException("An account with this email address already exists.")

        hashed = await hash_password(password)
        verification_token = generate_secure_token()

        user = await self.user_repo.create(
            {
                "email": email.lower().strip(),
                "hashed_password": hashed,
                "first_name": first_name.strip(),
                "last_name": last_name.strip(),
                "phone": phone,
                "role": role,
                "status": UserStatus.PENDING_VERIFICATION,
                "email_verification_token": verification_token,
            }
        )

        await self.audit_repo.log(
            event_type=AuditEventType.USER_CREATED,
            description=f"New user registered: {email}",
            user_id=user.id,
            ip_address=ip_address,
            metadata={"role": role.value},
        )

        logger.info("user.registered", user_id=str(user.id), email=email, role=role.value)
        return user

    # ──────────────────────────────────────────
    # Login / Authentication
    # ──────────────────────────────────────────

    async def authenticate_user(
        self,
        email: str,
        password: str,
        ip_address: str,
        user_agent: Optional[str] = None,
    ) -> Tuple[str, str, User]:
        """
        Authenticate credentials and return (access_token, refresh_token, user).
        Raises appropriate exceptions for all failure modes.
        """
        # Check brute-force lockout FIRST (before DB lookup — prevents timing oracle)
        await self._check_ip_lockout(ip_address)

        user = await self.user_repo.get_active_by_email(email)

        # Use constant-time comparison to prevent user enumeration
        if user is None:
            await self._record_failed_ip_attempt(ip_address)
            await self.audit_repo.log(
                event_type=AuditEventType.LOGIN_FAILED,
                description=f"Login attempt for unknown email: {email}",
                ip_address=ip_address,
                user_agent=user_agent,
                severity="warning",
            )
            raise UnauthorizedException("Invalid email or password.")

        # Check account status
        if user.status == UserStatus.SUSPENDED:
            raise ForbiddenException("Your account has been suspended. Contact support.")

        if user.is_locked:
            raise ForbiddenException(
                f"Account is temporarily locked due to too many failed attempts. "
                f"Try again after {user.locked_until.strftime('%H:%M UTC')}."
            )

        # Verify password
        is_valid = await verify_password(password, user.hashed_password)
        if not is_valid:
            count = await self.user_repo.increment_failed_attempts(user.id)
            await self._record_failed_ip_attempt(ip_address)

            await self.audit_repo.log(
                event_type=AuditEventType.LOGIN_FAILED,
                description=f"Failed login for {email} (attempt {count})",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"attempt_count": count},
                severity="warning",
            )

            # Lock after max attempts
            if count >= settings.auth.max_failed_attempts:
                locked_until = datetime.now(timezone.utc) + timedelta(
                    seconds=settings.auth.lockout_duration_seconds
                )
                await self.user_repo.lock_account(user.id, locked_until)
                await self.audit_repo.log(
                    event_type=AuditEventType.ACCOUNT_LOCKED,
                    description=f"Account locked after {count} failed attempts",
                    user_id=user.id,
                    ip_address=ip_address,
                    severity="critical",
                )
                raise ForbiddenException(
                    f"Account locked after {count} failed attempts. "
                    f"Try again in {settings.auth.lockout_duration_seconds // 60} minutes."
                )

            remaining = settings.auth.max_failed_attempts - count
            raise UnauthorizedException(
                f"Invalid email or password. {remaining} attempt(s) remaining."
            )

        # Detect suspicious login (new IP, unusual time, etc.)
        is_suspicious = await self._detect_suspicious_login(user, ip_address, user_agent)

        # Issue tokens
        access_token, _ = create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=user.role.value,
        )
        refresh_token, family, expires_at = create_refresh_token(user_id=str(user.id))

        await self.token_repo.create_token(
            user_id=user.id,
            token=refresh_token,
            family=family,
            expires_at=expires_at,
            ip_address=ip_address,
            device_info=user_agent,
        )

        await self.user_repo.update_last_login(user.id, ip_address)
        await self._clear_ip_lockout(ip_address)

        event_type = AuditEventType.SUSPICIOUS_LOGIN if is_suspicious else AuditEventType.LOGIN_SUCCESS
        await self.audit_repo.log(
            event_type=event_type,
            description=f"Successful login for {email}",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            severity="warning" if is_suspicious else "info",
        )

        logger.info(
            "user.login",
            user_id=str(user.id),
            ip=ip_address,
            suspicious=is_suspicious,
        )
        return access_token, refresh_token, user

    # ──────────────────────────────────────────
    # Token Refresh (Rotation)
    # ──────────────────────────────────────────

    async def refresh_tokens(
        self,
        refresh_token: str,
        ip_address: str,
        user_agent: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Rotate refresh token. Detects token reuse (theft).
        Returns (new_access_token, new_refresh_token).
        """
        try:
            payload = decode_refresh_token(refresh_token)
        except UnauthorizedException:
            raise

        family = payload.get("family")
        user_id = payload.get("sub")

        stored_token = await self.token_repo.get_by_token(refresh_token)

        if stored_token is None:
            # Token not in DB — could be theft if family exists with revoked tokens
            if family:
                await self.token_repo.revoke_family(family)
                logger.warning(
                    "security.token_reuse_detected",
                    family=family,
                    user_id=user_id,
                    ip=ip_address,
                )
            raise UnauthorizedException("Invalid refresh token.")

        if stored_token.is_revoked:
            # Token was already used — REUSE DETECTED → revoke whole family
            await self.token_repo.revoke_family(family)
            await self.audit_repo.log(
                event_type=AuditEventType.TOKEN_REVOKED,
                description="Token reuse detected — entire family revoked",
                user_id=stored_token.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                severity="critical",
                metadata={"family": family},
            )
            logger.warning(
                "security.refresh_token_reuse",
                family=family,
                user_id=user_id,
                ip=ip_address,
            )
            raise UnauthorizedException("Session invalidated due to suspicious activity.")

        if stored_token.is_expired:
            raise UnauthorizedException("Refresh token has expired. Please log in again.")

        # Fetch user
        user = await self.user_repo.get_by_id(stored_token.user_id)
        if not user or not user.is_active:
            raise UnauthorizedException("User account is not active.")

        # Revoke old token
        await self.token_repo.revoke_token(stored_token.id)

        # Issue new tokens (same family for rotation chain)
        new_access, _ = create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=user.role.value,
        )
        new_refresh, _, new_expires = create_refresh_token(
            user_id=str(user.id), family=family
        )

        await self.token_repo.create_token(
            user_id=user.id,
            token=new_refresh,
            family=family,
            expires_at=new_expires,
            ip_address=ip_address,
            device_info=user_agent,
        )

        await self.audit_repo.log(
            event_type=AuditEventType.TOKEN_REFRESHED,
            description="Token refreshed successfully",
            user_id=user.id,
            ip_address=ip_address,
        )

        return new_access, new_refresh

    # ──────────────────────────────────────────
    # Logout
    # ──────────────────────────────────────────

    async def logout(
        self,
        refresh_token: str,
        user_id: uuid.UUID,
        ip_address: str,
    ) -> None:
        """Revoke a single session (current device logout)."""
        stored = await self.token_repo.get_by_token(refresh_token)
        if stored and stored.user_id == user_id:
            await self.token_repo.revoke_token(stored.id)

        await self.audit_repo.log(
            event_type=AuditEventType.LOGOUT,
            description="User logged out",
            user_id=user_id,
            ip_address=ip_address,
        )

    async def logout_everywhere(
        self, user_id: uuid.UUID, ip_address: str
    ) -> None:
        """Revoke ALL sessions for a user (logout from all devices)."""
        await self.token_repo.revoke_all_for_user(user_id)
        await self.audit_repo.log(
            event_type=AuditEventType.LOGOUT,
            description="User logged out from all devices",
            user_id=user_id,
            ip_address=ip_address,
            severity="warning",
        )

    # ──────────────────────────────────────────
    # Password Management
    # ──────────────────────────────────────────

    async def change_password(
        self,
        user_id: uuid.UUID,
        current_password: str,
        new_password: str,
        ip_address: str,
    ) -> None:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundException("User not found.")

        if not await verify_password(current_password, user.hashed_password):
            raise UnauthorizedException("Current password is incorrect.")

        is_strong, violations = validate_password_strength(new_password)
        if not is_strong:
            raise BadRequestException("New password is too weak.", detail=violations)

        if await verify_password(new_password, user.hashed_password):
            raise BadRequestException("New password must differ from the current password.")

        new_hash = await hash_password(new_password)
        await self.user_repo.update_password(user_id, new_hash)

        # Revoke all refresh tokens — force re-login on all devices
        await self.token_repo.revoke_all_for_user(user_id)

        await self.audit_repo.log(
            event_type=AuditEventType.PASSWORD_CHANGED,
            description="Password changed — all sessions revoked",
            user_id=user_id,
            ip_address=ip_address,
            severity="warning",
        )

    async def request_password_reset(
        self, email: str, ip_address: str
    ) -> Optional[str]:
        """
        Initiate password reset. Returns reset token (send via email in production).
        Always succeeds to prevent user enumeration.
        """
        user = await self.user_repo.get_by_email(email)
        if not user:
            # Don't reveal whether email exists
            return None

        reset_token = generate_secure_token()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        await self.session.execute(
            __import__("sqlalchemy").update(
                __import__("app.db.models.user", fromlist=["User"]).User
            )
            .where(__import__("app.db.models.user", fromlist=["User"]).User.id == user.id)
            .values(
                password_reset_token=reset_token,
                password_reset_expires_at=expires_at,
            )
        )
        await self.session.flush()

        await self.audit_repo.log(
            event_type=AuditEventType.PASSWORD_RESET_REQUESTED,
            description=f"Password reset requested for {email}",
            user_id=user.id,
            ip_address=ip_address,
        )
        return reset_token

    async def complete_password_reset(
        self, token: str, new_password: str, ip_address: str
    ) -> None:
        from sqlalchemy import select
        from app.db.models.user import User as UserModel

        result = await self.session.execute(
            select(UserModel).where(UserModel.password_reset_token == token)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise BadRequestException("Invalid or expired reset token.")

        if not user.password_reset_expires_at or \
                datetime.now(timezone.utc) > user.password_reset_expires_at:
            raise BadRequestException("Reset token has expired. Please request a new one.")

        is_strong, violations = validate_password_strength(new_password)
        if not is_strong:
            raise BadRequestException("Password is too weak.", detail=violations)

        new_hash = await hash_password(new_password)
        await self.user_repo.update_password(user.id, new_hash)
        await self.token_repo.revoke_all_for_user(user.id)

        await self.audit_repo.log(
            event_type=AuditEventType.PASSWORD_RESET_COMPLETED,
            description="Password reset completed",
            user_id=user.id,
            ip_address=ip_address,
            severity="warning",
        )

    # ──────────────────────────────────────────
    # Email Verification
    # ──────────────────────────────────────────

    async def verify_email(self, token: str, ip_address: str) -> User:
        from sqlalchemy import select
        from app.db.models.user import User as UserModel

        result = await self.session.execute(
            select(UserModel).where(UserModel.email_verification_token == token)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise BadRequestException("Invalid or expired verification token.")

        if user.is_email_verified:
            raise BadRequestException("Email is already verified.")

        await self.user_repo.verify_email(user.id)
        await self.audit_repo.log(
            event_type=AuditEventType.EMAIL_VERIFIED,
            description=f"Email verified for {user.email}",
            user_id=user.id,
            ip_address=ip_address,
        )
        return user

    # ──────────────────────────────────────────
    # Brute-Force / Suspicious Login Helpers
    # ──────────────────────────────────────────

    async def _check_ip_lockout(self, ip_address: str) -> None:
        key = f"auth:ip_lock:{ip_address}"
        if await self.cache.exists(key):
            raise ForbiddenException(
                "Too many failed login attempts from this IP. Try again later."
            )

    async def _record_failed_ip_attempt(self, ip_address: str) -> None:
        key = f"auth:ip_fail:{ip_address}"
        count = await self.cache.increment(key)
        # Set TTL on first increment
        if count == 1:
            await self.cache.client.expire(
                self.cache._key(f"auth:ip_fail:{ip_address}"),
                settings.auth.login_rate_window,
            )
        if count >= settings.auth.login_rate_limit:
            lock_key = f"auth:ip_lock:{ip_address}"
            await self.cache.set_with_nx(
                f"auth:ip_lock:{ip_address}",
                "locked",
                ttl_seconds=settings.auth.lockout_duration_seconds,
            )

    async def _clear_ip_lockout(self, ip_address: str) -> None:
        await self.cache.delete(f"auth:ip_fail:{ip_address}")
        await self.cache.delete(f"auth:ip_lock:{ip_address}")

    async def _detect_suspicious_login(
        self, user: User, ip_address: str, user_agent: Optional[str]
    ) -> bool:
        """
        Heuristic suspicious login detection.
        Flags: new IP, unusual hour, different country (placeholder).
        Returns True if suspicious.
        """
        is_suspicious = False

        # New IP compared to last login
        if user.last_login_ip and user.last_login_ip != ip_address:
            is_suspicious = True
            logger.warning(
                "security.new_ip_login",
                user_id=str(user.id),
                old_ip=user.last_login_ip,
                new_ip=ip_address,
            )

        # Unusual hour (midnight to 5am UTC — banking heuristic)
        current_hour = datetime.now(timezone.utc).hour
        if current_hour < 5:
            is_suspicious = True

        return is_suspicious
