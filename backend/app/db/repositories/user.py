"""
User Repository
================
All database operations for User, RefreshToken, AuditLog.
No business logic here — pure data access.
"""

import hashlib
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import AuditEventType, AuditLog, RefreshToken, User, UserStatus
from app.db.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(
                and_(User.email == email.lower(), User.deleted_at.is_(None))
            )
        )
        return result.scalar_one_or_none()

    async def get_active_by_email(self, email: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(
                and_(
                    User.email == email.lower(),
                    User.deleted_at.is_(None),
                    User.status != UserStatus.SUSPENDED,
                )
            )
        )
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        result = await self.session.execute(
            select(User.id).where(User.email == email.lower())
        )
        return result.scalar_one_or_none() is not None

    async def increment_failed_attempts(self, user_id: uuid.UUID) -> int:
        """Increment failed login counter and return new count."""
        result = await self.session.execute(
            select(User.failed_login_attempts).where(User.id == user_id)
        )
        current = result.scalar_one_or_none() or 0
        new_count = current + 1
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(failed_login_attempts=new_count)
        )
        await self.session.flush()
        return new_count

    async def reset_failed_attempts(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(failed_login_attempts=0, locked_until=None)
        )
        await self.session.flush()

    async def lock_account(self, user_id: uuid.UUID, until: datetime) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(locked_until=until, status=UserStatus.LOCKED)
        )
        await self.session.flush()

    async def unlock_account(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                locked_until=None,
                failed_login_attempts=0,
                status=UserStatus.ACTIVE,
            )
        )
        await self.session.flush()

    async def update_last_login(
        self, user_id: uuid.UUID, ip_address: str
    ) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                last_login_at=datetime.now(timezone.utc),
                last_login_ip=ip_address,
                failed_login_attempts=0,
                locked_until=None,
            )
        )
        await self.session.flush()

    async def update_password(self, user_id: uuid.UUID, hashed_password: str) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                hashed_password=hashed_password,
                password_reset_token=None,
                password_reset_expires_at=None,
            )
        )
        await self.session.flush()

    async def set_verification_token(
        self, user_id: uuid.UUID, token: str
    ) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(email_verification_token=token)
        )
        await self.session.flush()

    async def verify_email(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                is_email_verified=True,
                email_verification_token=None,
                email_verified_at=datetime.now(timezone.utc),
                status=UserStatus.ACTIVE,
            )
        )
        await self.session.flush()


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(RefreshToken, session)

    @staticmethod
    def _hash_token(token: str) -> str:
        """Store only SHA-256 hash of the token, never plaintext."""
        return hashlib.sha256(token.encode()).hexdigest()

    async def create_token(
        self,
        user_id: uuid.UUID,
        token: str,
        family: str,
        expires_at: datetime,
        ip_address: Optional[str] = None,
        device_info: Optional[str] = None,
    ) -> RefreshToken:
        instance = RefreshToken(
            user_id=user_id,
            token_hash=self._hash_token(token),
            family=family,
            expires_at=expires_at,
            ip_address=ip_address,
            device_info=device_info,
        )
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def get_by_token(self, token: str) -> Optional[RefreshToken]:
        token_hash = self._hash_token(token)
        result = await self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke_token(self, token_id: uuid.UUID) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id)
            .values(is_revoked=True, revoked_at=datetime.now(timezone.utc))
        )
        await self.session.flush()

    async def revoke_family(self, family: str) -> None:
        """Revoke ALL tokens in a family — triggered on theft detection."""
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family == family)
            .values(is_revoked=True, revoked_at=datetime.now(timezone.utc))
        )
        await self.session.flush()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        """Revoke all tokens for a user — logout everywhere."""
        await self.session.execute(
            update(RefreshToken)
            .where(
                and_(
                    RefreshToken.user_id == user_id,
                    RefreshToken.is_revoked.is_(False),
                )
            )
            .values(is_revoked=True, revoked_at=datetime.now(timezone.utc))
        )
        await self.session.flush()

    async def get_active_count(self, user_id: uuid.UUID) -> int:
        from sqlalchemy import func
        result = await self.session.execute(
            select(func.count())
            .select_from(RefreshToken)
            .where(
                and_(
                    RefreshToken.user_id == user_id,
                    RefreshToken.is_revoked.is_(False),
                    RefreshToken.expires_at > datetime.now(timezone.utc),
                )
            )
        )
        return result.scalar_one()


class AuditLogRepository(BaseRepository[AuditLog]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AuditLog, session)

    async def log(
        self,
        event_type: AuditEventType,
        description: str,
        user_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict] = None,
        severity: str = "info",
    ) -> AuditLog:
        instance = AuditLog(
            event_type=event_type,
            description=description,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata,
            severity=severity,
        )
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def get_recent_for_user(
        self, user_id: uuid.UUID, limit: int = 50
    ) -> List[AuditLog]:
        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.user_id == user_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_security_events(
        self, limit: int = 100
    ) -> List[AuditLog]:
        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.severity.in_(["warning", "critical"]))
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
