"""
Base Model Mixins
==================
Reusable SQLAlchemy mixins applied to every domain model.
Provides: UUID PK, timestamps, soft delete, audit fields.

All domain models extend TimestampMixin + SoftDeleteMixin via Base.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────
# Declarative Base (single source of truth)
# ──────────────────────────────────────────────

class Base(DeclarativeBase):
    """
    Shared declarative base for ALL SQLAlchemy models.
    Import this — never create another DeclarativeBase.
    """
    pass


# ──────────────────────────────────────────────
# Mixins
# ──────────────────────────────────────────────

class UUIDPrimaryKeyMixin:
    """UUID v4 primary key — database-agnostic, no collision risk."""
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )


class TimestampMixin:
    """
    Automatic created_at + updated_at timestamps.
    updated_at is refreshed on every UPDATE via server-side func.now().
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """
    Soft-delete support. Deleted records are hidden, not removed.
    Use .is_deleted property or filter on deleted_at IS NULL.
    """
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )
    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, deleted_by: Optional[uuid.UUID] = None) -> None:
        self.deleted_at = utcnow()
        self.deleted_by = deleted_by


class AuditMixin:
    """
    Tracks who created and last modified a record.
    created_by / updated_by reference users.id (not FK — avoids circular deps).
    """
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class FullAuditMixin(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, AuditMixin):
    """
    Convenience mixin — combines all audit fields.
    Use this for all primary domain entities.
    """
    pass
