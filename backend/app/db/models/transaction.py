"""
Transaction Model
==================
Immutable financial transaction records.
Transactions are NEVER updated or deleted — only appended.
Reversals create a new offsetting transaction.
"""

import uuid
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    CheckConstraint, Enum, ForeignKey, Index,
    Numeric, String, Text, Boolean
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TransactionType(str, PyEnum):
    CREDIT = "credit"
    DEBIT = "debit"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    LOAN_DISBURSEMENT = "loan_disbursement"
    LOAN_REPAYMENT = "loan_repayment"
    FEE = "fee"
    INTEREST = "interest"
    REVERSAL = "reversal"
    REFUND = "refund"


class TransactionStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REVERSED = "reversed"
    DISPUTED = "disputed"
    ON_HOLD = "on_hold"


class TransactionChannel(str, PyEnum):
    NET_BANKING = "net_banking"
    MOBILE_APP = "mobile_app"
    ATM = "atm"
    BRANCH = "branch"
    API = "api"
    UPI = "upi"
    NEFT = "neft"
    RTGS = "rtgs"
    IMPS = "imps"
    SWIFT = "swift"


class Transaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Immutable transaction record. No soft delete — financial records are permanent.
    Reversals are handled by creating a new REVERSAL type transaction.
    """
    __tablename__ = "transactions"

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
    loan_application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("loan_applications.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Reference numbers
    reference_number: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    external_reference: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    reversal_of_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Financial
    amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    exchange_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)
    amount_in_base_currency: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4), nullable=True)
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False, default=0)

    # Account details (denormalized for immutability)
    from_account: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    to_account: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    from_bank_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    to_bank_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Classification
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType), nullable=False, index=True
    )
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus), nullable=False,
        default=TransactionStatus.PENDING, index=True
    )
    channel: Mapped[TransactionChannel] = mapped_column(
        Enum(TransactionChannel), nullable=False,
        default=TransactionChannel.API
    )
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    narration: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Fraud / risk
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    risk_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    fraud_report_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Processing
    processed_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    settlement_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    device_fingerprint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Flexible metadata
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    bank: Mapped[Optional["Bank"]] = relationship("Bank", foreign_keys=[bank_id])
    loan_application: Mapped[Optional["LoanApplication"]] = relationship(
        "LoanApplication", foreign_keys=[loan_application_id]
    )
    reversal_of: Mapped[Optional["Transaction"]] = relationship(
        "Transaction", foreign_keys=[reversal_of_id], remote_side="Transaction.id"
    )
    fraud_reports: Mapped[list["FraudReport"]] = relationship(
        "FraudReport", back_populates="transaction",
        primaryjoin="FraudReport.transaction_id == Transaction.id"
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("fee_amount >= 0", name="ck_transactions_fee_non_negative"),
        Index("ix_transactions_user_created", "user_id", "created_at"),
        Index("ix_transactions_status_type", "status", "transaction_type"),
        Index("ix_transactions_reference", "reference_number"),
        Index("ix_transactions_flagged", "is_flagged"),
        Index("ix_transactions_created_at", "created_at"),
        Index("ix_transactions_category", "category"),
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} ref={self.reference_number} "
            f"amount={self.amount} {self.currency} status={self.status}>"
        )
