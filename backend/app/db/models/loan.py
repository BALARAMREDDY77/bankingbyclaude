"""
Loan Application Model
========================
Tracks the complete lifecycle of a loan application —
from submission through underwriting, approval, and disbursement.
"""

import uuid
from decimal import Decimal
from enum import Enum as PyEnum
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint, Enum, ForeignKey,
    Index, Integer, Numeric, String, Text, Boolean
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, FullAuditMixin


class LoanType(str, PyEnum):
    PERSONAL = "personal"
    HOME = "home"
    AUTO = "auto"
    EDUCATION = "education"
    BUSINESS = "business"
    GOLD = "gold"
    AGRICULTURAL = "agricultural"
    MEDICAL = "medical"
    CREDIT_CARD = "credit_card"


class LoanStatus(str, PyEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    DOCUMENT_PENDING = "document_pending"
    UNDER_REVIEW = "under_review"
    AI_ASSESSMENT = "ai_assessment"
    CREDIT_CHECK = "credit_check"
    APPROVED = "approved"
    CONDITIONALLY_APPROVED = "conditionally_approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    DISBURSED = "disbursed"
    ACTIVE = "active"
    CLOSED = "closed"
    DEFAULTED = "defaulted"
    NPA = "npa"          # Non-Performing Asset


class LoanPurpose(str, PyEnum):
    HOME_PURCHASE = "home_purchase"
    HOME_RENOVATION = "home_renovation"
    VEHICLE_PURCHASE = "vehicle_purchase"
    EDUCATION = "education"
    MEDICAL = "medical"
    WEDDING = "wedding"
    TRAVEL = "travel"
    DEBT_CONSOLIDATION = "debt_consolidation"
    BUSINESS_EXPANSION = "business_expansion"
    WORKING_CAPITAL = "working_capital"
    OTHER = "other"


class EmploymentType(str, PyEnum):
    SALARIED = "salaried"
    SELF_EMPLOYED = "self_employed"
    BUSINESS_OWNER = "business_owner"
    FREELANCER = "freelancer"
    RETIRED = "retired"
    STUDENT = "student"
    UNEMPLOYED = "unemployed"


class LoanApplication(Base, FullAuditMixin):
    __tablename__ = "loan_applications"

    # Parties
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    bank_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("banks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_officer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Application identity
    application_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    loan_type: Mapped[LoanType] = mapped_column(
        Enum(LoanType), nullable=False, index=True
    )
    purpose: Mapped[LoanPurpose] = mapped_column(
        Enum(LoanPurpose), nullable=False
    )
    status: Mapped[LoanStatus] = mapped_column(
        Enum(LoanStatus), nullable=False,
        default=LoanStatus.DRAFT, index=True
    )

    # Financials requested
    requested_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    requested_tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_interest_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    # Financials approved
    approved_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    approved_tenure_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approved_interest_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    emi_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    processing_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)

    # Applicant financial profile
    employment_type: Mapped[Optional[EmploymentType]] = mapped_column(
        Enum(EmploymentType), nullable=True
    )
    employer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    monthly_income: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    annual_income: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    existing_emi: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    credit_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    debt_to_income_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)

    # AI assessment
    ai_risk_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    ai_recommendation: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ai_confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    ai_assessed_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Decision
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    conditions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    decided_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    decided_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Disbursement
    disbursed_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    disbursed_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    disbursement_account: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    maturity_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Repayment tracking
    outstanding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    total_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    overdue_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    overdue_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_payment_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Flags
    is_priority: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_physical_verification: Mapped[bool] = mapped_column(Boolean, default=False)

    # Collateral / property (for home/auto loans)
    collateral_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    collateral_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    collateral_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Flexible metadata
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    bank: Mapped[Optional["Bank"]] = relationship("Bank", back_populates="loan_applications")
    assigned_officer: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[assigned_officer_id]
    )
    documents: Mapped[List["UploadedDocument"]] = relationship(
        "UploadedDocument", back_populates="loan_application"
    )
    fraud_reports: Mapped[List["FraudReport"]] = relationship(
        "FraudReport", back_populates="loan_application"
    )
    ai_reports: Mapped[List["AIReport"]] = relationship(
        "AIReport", back_populates="loan_application"
    )
    transactions: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="loan_application",
        foreign_keys="Transaction.loan_application_id"
    )
    alerts: Mapped[List["Alert"]] = relationship(
        "Alert", back_populates="loan_application"
    )

    __table_args__ = (
        CheckConstraint("requested_amount > 0", name="ck_loan_amount_positive"),
        CheckConstraint("requested_tenure_months > 0", name="ck_loan_tenure_positive"),
        CheckConstraint(
            "credit_score IS NULL OR (credit_score >= 300 AND credit_score <= 900)",
            name="ck_loan_credit_score_range",
        ),
        Index("ix_loans_user_status", "user_id", "status"),
        Index("ix_loans_bank_status", "bank_id", "status"),
        Index("ix_loans_type_status", "loan_type", "status"),
        Index("ix_loans_application_number", "application_number"),
        Index("ix_loans_created_at", "created_at"),
        Index("ix_loans_ai_risk_score", "ai_risk_score"),
    )

    def __repr__(self) -> str:
        return (
            f"<LoanApplication id={self.id} "
            f"number={self.application_number} "
            f"type={self.loan_type} status={self.status}>"
        )
