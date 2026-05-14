"""
Fraud Report Model
===================
Records suspected or confirmed fraud events.
Linked to transactions, loan applications, and users.
Supports the full fraud investigation workflow.
"""

import uuid
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean, Enum, ForeignKey, Index,
    Numeric, String, Text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, FullAuditMixin


class FraudType(str, PyEnum):
    IDENTITY_THEFT = "identity_theft"
    DOCUMENT_FORGERY = "document_forgery"
    SYNTHETIC_IDENTITY = "synthetic_identity"
    ACCOUNT_TAKEOVER = "account_takeover"
    LOAN_STACKING = "loan_stacking"
    MONEY_LAUNDERING = "money_laundering"
    PHISHING = "phishing"
    TRANSACTION_FRAUD = "transaction_fraud"
    INSIDER_FRAUD = "insider_fraud"
    APPLICATION_FRAUD = "application_fraud"
    BUST_OUT = "bust_out"
    OTHER = "other"


class FraudSeverity(str, PyEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FraudStatus(str, PyEnum):
    OPEN = "open"
    UNDER_INVESTIGATION = "under_investigation"
    ESCALATED = "escalated"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"
    REPORTED_TO_AUTHORITIES = "reported_to_authorities"


class FraudSource(str, PyEnum):
    AI_DETECTION = "ai_detection"
    RULE_ENGINE = "rule_engine"
    MANUAL_REVIEW = "manual_review"
    USER_REPORT = "user_report"
    BANK_REPORT = "bank_report"
    REGULATORY = "regulatory"
    THIRD_PARTY = "third_party"


class FraudReport(Base, FullAuditMixin):
    __tablename__ = "fraud_reports"

    # Subject
    reported_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    loan_application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Classification
    fraud_type: Mapped[FraudType] = mapped_column(
        Enum(FraudType), nullable=False, index=True
    )
    severity: Mapped[FraudSeverity] = mapped_column(
        Enum(FraudSeverity), nullable=False,
        default=FraudSeverity.MEDIUM, index=True
    )
    status: Mapped[FraudStatus] = mapped_column(
        Enum(FraudStatus), nullable=False,
        default=FraudStatus.OPEN, index=True
    )
    source: Mapped[FraudSource] = mapped_column(
        Enum(FraudSource), nullable=False,
        default=FraudSource.AI_DETECTION
    )

    # Report details
    report_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    indicators: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Financial impact
    estimated_loss_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    actual_loss_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    recovered_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    # AI detection
    ai_confidence_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    ai_model_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ai_detected_patterns: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Investigation
    investigation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Flags
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    account_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    fir_filed: Mapped[bool] = mapped_column(Boolean, default=False)
    fir_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Relationships
    reported_user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[reported_user_id]
    )
    transaction: Mapped[Optional["Transaction"]] = relationship(
        "Transaction", back_populates="fraud_reports",
        foreign_keys=[transaction_id]
    )
    loan_application: Mapped[Optional["LoanApplication"]] = relationship(
        "LoanApplication", back_populates="fraud_reports"
    )
    assigned_reviewer: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[assigned_reviewer_id]
    )

    __table_args__ = (
        Index("ix_fraud_type_status", "fraud_type", "status"),
        Index("ix_fraud_severity_status", "severity", "status"),
        Index("ix_fraud_user", "reported_user_id"),
        Index("ix_fraud_created_at", "created_at"),
        Index("ix_fraud_report_number", "report_number"),
    )

    def __repr__(self) -> str:
        return (
            f"<FraudReport id={self.id} "
            f"number={self.report_number} "
            f"type={self.fraud_type} severity={self.severity}>"
        )
