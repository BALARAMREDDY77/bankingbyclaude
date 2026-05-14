"""
Bank Model
===========
Represents a banking institution on the platform.
A bank has many accounts, loan products, and employees.
"""

import uuid
from decimal import Decimal
from enum import Enum as PyEnum
from typing import List, Optional

from sqlalchemy import (
    Boolean, Enum, Index, Numeric, String, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, FullAuditMixin


class BankStatus(str, PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    UNDER_REVIEW = "under_review"
    CLOSED = "closed"


class BankTier(str, PyEnum):
    TIER_1 = "tier_1"       # Major national banks
    TIER_2 = "tier_2"       # Regional banks
    TIER_3 = "tier_3"       # Local / community banks
    NBFC = "nbfc"           # Non-banking financial company
    COOPERATIVE = "cooperative"


class Bank(Base, FullAuditMixin):
    __tablename__ = "banks"

    # Identity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(500), nullable=False)
    short_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    ifsc_prefix: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    swift_code: Mapped[Optional[str]] = mapped_column(String(11), nullable=True)
    routing_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Classification
    tier: Mapped[BankTier] = mapped_column(
        Enum(BankTier), nullable=False, default=BankTier.TIER_2
    )
    status: Mapped[BankStatus] = mapped_column(
        Enum(BankStatus), nullable=False, default=BankStatus.ACTIVE, index=True
    )
    is_partner: Mapped[bool] = mapped_column(Boolean, default=False)

    # Regulatory
    license_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    regulator: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    regulated_since: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Contact
    headquarters_city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    headquarters_country: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    support_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    support_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Financial metrics (updated periodically)
    total_assets_crore: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    credit_rating: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Flexible metadata
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)

    # Relationships
    loan_applications: Mapped[List["LoanApplication"]] = relationship(
        "LoanApplication", back_populates="bank", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_banks_short_code", "short_code"),
        Index("ix_banks_status_tier", "status", "tier"),
        Index("ix_banks_country", "headquarters_country"),
        UniqueConstraint("short_code", name="uq_banks_short_code"),
    )

    def __repr__(self) -> str:
        return f"<Bank id={self.id} name={self.name} tier={self.tier}>"
